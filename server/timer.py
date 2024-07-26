import asyncio
import time

CHECK_FREQUENCY = .1

def create_timer(duration: float):
	now = time.time()
	return {
		"start": now,
		"end": now + duration,
		"pause_start": None,
		"active": True,
		"winner": None
	}

async def run_timer(duration: float, checker: callable , callback: callable, parameters: dict):
	proceed = True
	while (proceed):
		await asyncio.sleep(duration)
		#  catch if the room is empty/deleted but timer is still going (gracefully close the timer)
		try:
			proceed, duration = checker(time.time(), **parameters)
		except TypeError:
			break
	if (duration == 0):
		await callback(**parameters)