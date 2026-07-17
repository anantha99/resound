import assert from "node:assert/strict";
import { test } from "node:test";

import { barChart, deltaDisplay, sparklinePath } from "./viewModels.ts";

test("deltaDisplay renders a neutral flat treatment when delta is 0", () => {
  const d = deltaDisplay(0, { unit: "pt", flatText: "0pt · flat" });
  assert.equal(d.arrow, "→");
  assert.equal(d.tone, "neutral");
  assert.equal(d.text, "0pt · flat");
});

test("deltaDisplay renders a rising positive delta", () => {
  const d = deltaDisplay(14, { unit: "pt", upIsGood: true, flatText: "0pt · flat" });
  assert.equal(d.arrow, "↑");
  assert.equal(d.tone, "positive");
  assert.equal(d.text, "14pt");
});

test("deltaDisplay renders a falling delta as negative tone", () => {
  const d = deltaDisplay(-17, { unit: "pt", upIsGood: true, flatText: "0pt · flat" });
  assert.equal(d.arrow, "↓");
  assert.equal(d.tone, "negative");
  assert.equal(d.text, "17pt");
});

test("deltaDisplay flips tone when up is bad (critical)", () => {
  const up = deltaDisplay(3, { signed: true, suffix: " vs prev", upIsGood: false, flatText: "no change" });
  assert.equal(up.arrow, "↑");
  assert.equal(up.tone, "negative");
  assert.equal(up.text, "+3 vs prev");

  const down = deltaDisplay(-5, { signed: true, suffix: " vs prev", upIsGood: false, flatText: "no change" });
  assert.equal(down.arrow, "↓");
  assert.equal(down.tone, "positive");
  assert.equal(down.text, "-5 vs prev");
});

test("sparklinePath returns a flat mid-line for empty / single-point series", () => {
  assert.equal(sparklinePath([], 70, 18), "M0,9 L70,9");
  assert.equal(sparklinePath([5], 70, 18), "M0,9 L70,9");
});

test("sparklinePath returns a flat mid-line for all-equal series with no NaN", () => {
  const path = sparklinePath([3, 3, 3], 70, 18);
  assert.ok(!path.includes("NaN"));
  assert.ok(path.startsWith("M0,"));
  // all points at the same y
  const ys = path.split(" ").map(p => p.split(",")[1]);
  assert.equal(new Set(ys).size, 1);
});

test("sparklinePath scales higher values to the top of the viewBox", () => {
  const path = sparklinePath([0, 10], 70, 18);
  assert.ok(!path.includes("NaN"));
  const points = path.split(" ").map(p => p.replace(/[ML]/, "").split(",").map(Number));
  // first point (value 0, min) should be lower on screen (higher y) than last (value 10, max)
  assert.ok(points[0][1] > points[1][1]);
  assert.equal(points[0][0], 0);
  assert.equal(points[1][0], 70);
});

test("barChart returns no rects for an empty series", () => {
  assert.deepEqual(barChart([], 70, 18), []);
});

test("barChart slots bars evenly and scales the tallest to full height", () => {
  const bars = barChart([0, 1, 2], 60, 18);
  assert.equal(bars.length, 3);
  // Bars are left-to-right in slot order.
  assert.ok(bars[0].x < bars[1].x && bars[1].x < bars[2].x);
  // Empty bucket renders a faint 1px stub; tallest count reaches full height.
  assert.equal(bars[0].height, 1);
  assert.equal(bars[0].opacity, "0.25");
  assert.equal(bars[2].height, 18);
});
