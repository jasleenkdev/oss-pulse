import {html} from "npm:htl";

export const integer = (value) => (value == null ? "n/a" : Math.round(value).toLocaleString("en-US"));

export const percent = (value, digits = 1) =>
  value == null ? "n/a" : `${(value * 100).toFixed(digits)}%`;

export const hours = (value) => {
  if (value == null) return "n/a";
  if (value < 1) return `${Math.round(value * 60)} min`;
  if (value < 48) return `${value.toFixed(1)} h`;
  return `${(value / 24).toFixed(1)} d`;
};

export const tile = (label, value, note) =>
  html`<div class="tile"><div class="label">${label}</div><div class="value">${value}</div>${
    note ? html`<div class="tile-note">${note}</div>` : ""
  }</div>`;

export const legend = (items) =>
  html`<div class="legend">${items.map(
    ([name, color]) => html`<span><i style=${`background:${color}`}></i>${name}</span>`
  )}</div>`;
