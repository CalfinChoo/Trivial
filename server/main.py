from fastapi import (
    FastAPI, 
    Request,
    Response
)
from fastapi.middleware.cors import CORSMiddleware
from functools import lru_cache
import uvicorn
from socketio import AsyncServer, ASGIApp
from socketio.exceptions import ConnectionRefusedError

from room_manager import RoomManager
from session_manager import SessionManager
from game_manager import GameManager
from config import Settings
from timer import run_timer

# built-in libraries
import random
import string
from uuid import uuid4
import json
import asyncio
import time

@lru_cache
def get_settings():
    return Settings()
settings: Settings = get_settings()

# setup socketio
sio = AsyncServer(cors_allowed_origins=[], async_mode="asgi", ping_timeout=500, ping_interval=2500)
socket_app = ASGIApp(sio)

# setup fastapi app
app = FastAPI()
# Cors middleware setup
origins = [
    "http://localhost:4200", #frontend url
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/socket.io", socket_app)

# session and room managers
room_manager = RoomManager()
session_manager = SessionManager()
game_manager = GameManager()

'''
To connect 1st time:
1. host a room
    a. get a room id
    b. make a username
2. create_session(room_id) to create and get session_id
3. setup socket with session_id 
4. connect socket and join room

To reconnect from a disconnect:

'''

# @app.get("/api/rooms")
# async def get_rooms():
#     rooms = room_manager.get_rooms()
#     return {"rooms": rooms}

@app.get("/api/valid_room")
async def valid_room(room_id):
    return room_manager.is_valid_room(room_id)

@app.get("/api/create_session/")
async def create_session(request: Request):
    # Create a session id to identify each client
    session_id = request.cookies.get("session_id")
    room_id = request.query_params.get("room_id")
    username = request.query_params.get("username")
    if not session_id or not session_manager.get_session_id_exists(session_id):
        # session_id = str(uuid4())
        session_id = session_manager.create_session(room_id, username)
        response = Response(content=json.dumps({"session_id": session_id, "room_id": room_id, "reconnect": False}), media_type="application/json")
        response.set_cookie(key="session_id", value=session_id, httponly=True)
        return response
    return {"session_id": session_id, "room_id": session_manager.get_session(session_id)["room_id"], "reconnect": True}

@app.get("/api/get_session/")
async def get_session(request: Request):
    session_id = request.cookies.get("session_id")
    if not session_id or not session_manager.get_session_id_exists(session_id):
        response = Response(content=json.dumps({"session_id": None, "room_id": None, "reconnect": False}), media_type="application/json")
        response.delete_cookie(key="session_id", httponly=True)
        return response
    return {"session_id": session_id, "room_id": session_manager.get_session(session_id)["room_id"], "reconnect": True}

@app.get("/api/create_room_id")
async def create_room_id():
    room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=settings.room_id_length))
    rooms = room_manager.get_rooms()
    while room_id in rooms:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=settings.room_id_length))
    return {"room_id": room_id}

@app.get("/api/is_host")
async def is_host(session_id: str):
    room_id = session_manager.get_room_id(session_id)
    return {"is_host": room_manager.is_host(room_id, session_id)}

'''
    Socket.io events
'''

def getRoom(sid):
    return list(set(sio.manager.get_rooms(sid, "/")).difference({sid}))[0]

def get_ordered_players(players, session_info = False):
    if (not session_info):
        return sorted(session_manager.get_sessions(players), key=lambda s: s["timestamp"])
    return sorted(players, key=lambda s: s["timestamp"])   

async def send_players(room_id):
    room = room_manager.get_room_by_id(room_id)
    if (not room):
        return
    usernames = [i["username"] for i in get_ordered_players(room["curr_connections"])]
    await sio.emit("players", usernames, room=room_id)

async def send_game_state(room_id: str, state = None):
    if (state is None):
        state = game_manager.get_game_state(room_id)
    await sio.emit("game_state", state, room=room_id)

async def send_board_data(room_id:str):
    '''
        Sends the list of category titles
        And a list of the prices of clues
    '''
    await sio.emit("board_data", game_manager.get_board_info(room_id))

async def send_player_cash(room_id: str):
    room = room_manager.get_room_by_id(room_id)
    if (not room):
        return
    session_id = [i["session_id"] for i in get_ordered_players(room["curr_connections"])]
    return game_manager.get_player_cash(room_id, session_id)

async def send_picker(room_id: str, picker_session_id = None):
    '''
        sends to the sid of the person who will pick
        also sends the index of the person to pick
    '''
    if (not picker_session_id):
        picker_session_id = game_manager.get_picker(room_id)
    sid = session_manager.get_sid(picker_session_id)
    await sio.emit("picker", True, to=sid)
    room = room_manager.get_room_by_id(room_id)
    players = [i["session_id"] for i in get_ordered_players(room["curr_connections"])]
    await sio.emit("picker_index", players.index(picker_session_id), room=room_id)


async def handle_leaving_room(room_id: str, session_id: str):
    '''
        Leaves the room in the database (handles things like the new host and new picker)
    '''
    host, picker = room_manager.leave_room(room_id, session_id, session_manager)
    if (host):
        await sio.emit("host", to=host)
    if (picker):
        print("picker:", picker)
        await send_picker(room_id, picker)
    await send_players(room_id)
    # needs handle sending player cash and if someone leaves in the clue game state

async def send_timer(room_id: str, timer_name: str, timer_data: dict = None):
    if (not timer_data):
        await sio.emit(timer_name, timer_data, room=room_id)
    await sio.emit(timer_name, room_manager.get_timer(room_id, timer_name), room=room_id)

@sio.event
async def connect(sid, environ, auth):
    print("connect ", sid)
    session_id = auth['session_id']
    session = session_manager.get_session(session_id)
    if not session:
        raise ConnectionRefusedError('authentication failed')
    session_manager.update_session(session_id, sid)
    print(auth)

@sio.event
async def disconnect(sid):
    room = session_manager.get_room_by_sid(sid)
    if room:
        await handle_leaving_room(room["room_id"], room["session_id"])
    print('disconnect ', sid)

@sio.event
async def join_room(sid, data):
    room_id = data["room_id"]
    session_id = data['session_id']
    username = session_manager.get_username(session_id)
    room_manager.join_room(room_id, session_id)
    await sio.enter_room(sid, room_id)

    print(f"User {username} joined room {room_id}")

    # Send a status response to the client
    await sio.emit("join_room_status", {"status": "success"}, room=room_id)
    await send_players(room_id)

@sio.event
async def rejoin_room(sid, data):
    room_id = data["room_id"]
    session_id = data["session_id"]
    # username = room_manager.get_room_by_id(room_id)["all_connections"][session_id]["username"]
    username = session_manager.get_username(session_id)

    room_manager.join_room(room_id, session_id)
    await sio.enter_room(sid, room_id)

    await sio.emit("rejoin_room_status", {"status": "success"}, room=room_id)

@sio.event
async def leave_room(sid, data):
    '''
        Expects data to be a dict with keys "room_id" and "session_id"
    '''
    room_id = data['room_id']
    session_id = data['session_id']

    await handle_leaving_room(room_id, session_id)

    # remove session and remove from sio room
    session_manager.delete_session(session_id)
    await sio.leave_room(sid, room_id)

    print(f"User {session_id} left room {room_id}")

@sio.event
async def get_game_state(sid, room_id):
    return room_manager.get_room_by_id(room_id)["state"]

@sio.event
async def get_categories(sid, data):
    return game_manager.get_game_categories(data["room_id"])

@sio.event
async def start_game(sid, data):
    room_id, session_id, num_categories, num_clues = data["room_id"], data["session_id"], data["num_categories"], data["num_clues"]
    if (room_manager.is_host(room_id, session_id)):
        await send_game_state(room_id, "generating")
        game_manager.init_game(room_id, room_manager.get_room_by_id(room_id), num_categories, num_clues)
        game_manager.start_game(room_id)
    await send_game_state(room_id, "board")
    await send_board_data(room_id)
    await send_picker(room_id)

#### Timer settings ####
# in seconds

picked_time = 2 # time that the board flickers over the picked item
answer_time = 6 # time that a user gets to submit an answer
buzz_in_time = 10 # time that users get to buzz-in for a clue

### in-game events ####

async def finish_clue(room_id: str):
    await sio.emit("game_state", "board", room=room_id)

@sio.event
async def board_choice(sid, data):
    '''
        Receives the picked clue card from the picker and sends out the clue to all the people in the room.
    '''
    print("board choice", data)
    room_id, session_id, category_idx, clue_idx = data["room_id"], data["session_id"], data["category_idx"], data["clue_idx"]
    clue = game_manager.pick(session_id, room_id, str(category_idx), str(clue_idx))
    if (clue is None):
        return

    # send chosen coords and then send the clue itself
    await sio.emit("picking", {"category_idx": category_idx, "clue_idx":clue_idx, "duration": picked_time}, room=room_id)
    await asyncio.sleep(picked_time)

    # start the timer for hitting the buzzer
    timer = game_manager.init_buzz_in_timer(room_id, buzz_in_time)
    await sio.emit("game_state", "clue", room=room_id)
    await sio.emit("clue", {"clue": clue, "duration": buzz_in_time}, room=room_id)
    
    await run_timer(buzz_in_time, game_manager.check_buzz_in_timer, finish_clue, {"room_id": room_id})
    
@sio.event
async def buzz_in(sid, data):
    '''
        someone buzzes in on a clue
    '''
    room_id, session_id = data["room_id"], data["session_id"]
    passed = game_manager.handle_buzz_in(room_id, session_id)
    print(passed)
    if (not passed):
        return
    game_manager.pause_buzz_in_timer(room_id)
    await sio.emit("paused", room=room_id)

    room = room_manager.get_room_by_id(room_id)
    sessions = session_manager.get_sessions(room["curr_connections"])
    players = get_ordered_players(sessions, True)
    buzzer_index, buzzer_sid = None, None
    for p in range(len(players)):
        if (players[p]['session_id'] == session_id):
            buzzer_index = p
            buzzer_sid = players[p]['curr_sid']
    await sio.emit("someone_answering", {"who": buzzer_index}, room=room_id)
    await sio.emit("answering", {"duration": answer_time}, to=buzzer_sid)

async def answer_clue(sid, data):
    room_id, session_id, answer = data["room_id"], data["session_id"], data["answer"]

    # restart the timer
    # game_manager.restart

if __name__ == "__main__":
    uvicorn.run(app, host = "localhost", port = 8000, log_level='debug', access_log=True)