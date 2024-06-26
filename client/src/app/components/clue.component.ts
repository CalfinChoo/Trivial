import { Component, EventEmitter, Input, Output } from '@angular/core';
// import { NgOptimizedImage } from '@angular/common';
import { PageStates } from '../app.component';
import { NgClass, NgForOf } from '@angular/common';
import { Player } from './game.component';

enum BannerStates {
  Empty = "empty",
  Green = "green",
  Red = "red",
  AltAnswering = "altanswering",
  Answering = "answering"
}

@Component({
  selector: 'clue-view',
  standalone: true,
  imports: [NgForOf, NgClass],
  templateUrl: '../components_html/clue.component.html',
  styleUrl: '../components_css/clue.component.css',
})
export class ClueComponent {
  @Input() players!: Player[];
  @Output() gameStateChange = new EventEmitter<boolean>();

  BannerType = BannerStates
  banner = BannerStates.AltAnswering;

  bannerText = "Who/What is Berlin?";
  answeringText = "Team 1 is answering"

  // temp clue
  clue =
    'This city, known for its stunning architecture and rich history, is home to the iconic Brandenburg Gate and the Reichstag building.';
}
