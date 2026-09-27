const { test } = require('node:test');
const assert = require('node:assert/strict');
const { positionEvents, scheduleSignature, groupAlternatives } = require('../static/timetable.js');
const event = (start, end, weeks = [1], day = 0) => ({ course_id: String(start), start, end, weeks, day });

test('only connected overlaps share width; other times and days remain full width', () => {
  const result = positionEvents([event(1, 2), event(1, 2, [2]), event(6, 7), event(1, 2, [1], 1)]);
  assert.deepEqual(result.map(e => e.laneCount), [2, 2, 1, 1]);
  assert.deepEqual(result.map(e => e.lane), [0, 1, 0, 0]);
});
test('a connected chain reuses lanes and all cards fit without collisions', () => {
  const result = positionEvents([event(1, 3), event(3, 5), event(5, 7), event(8, 9)]);
  assert.deepEqual(result.map(e => [e.lane, e.laneCount]), [[0, 2], [1, 2], [0, 2], [0, 1]]);
});
test('single week removes out-of-week classes before assigning widths', () => {
  const events = [event(1, 2, [1, 3]), event(1, 2, [2, 4])];
  const result = positionEvents(events, 3);
  assert.equal(result.length, 1);
  assert.equal(result[0].laneCount, 1);
  assert.deepEqual(result[0].event.weeks, [1, 3]);
  assert.equal(positionEvents(events, 5).length, 0);
});
test('bad period, day or empty week data does not create phantom rows', () => {
  assert.equal(positionEvents([event(0, 2), event(1, 15), event(1, 2, []), event(1, 2, [1], 7)]).length, 0);
});
test('same-time comparison ignores teachers, rooms, order and equivalent splits', () => {
  const original = [{...event(1, 2, [1, 2]), teacher:'A', room:'R1'}, event(6, 7, [3], 3)];
  const split = [event(6, 7, [3], 3), event(1, 1, [2, 1]), {...event(2, 2, [1, 2]), teacher:'B', room:'R2'}];
  assert.equal(scheduleSignature(original), scheduleSignature(split));
});
test('same-time comparison checks the second meeting and exact week sets', () => {
  const original = [event(1, 2, [1, 3]), event(6, 7, [3], 3)];
  assert.notEqual(scheduleSignature(original), scheduleSignature([event(1, 2, [2, 4]), original[1]]));
  assert.notEqual(scheduleSignature(original), scheduleSignature([original[0], event(6, 7, [3], 4)]));
  assert.notEqual(scheduleSignature(original), scheduleSignature([original[0]]));
});
test('alternative groups include every option, keep current first and do not equate unknown schedules', () => {
  const options = [
    {id:'other', events:[event(3, 4)]}, {id:'same', events:[event(1, 2)]},
    {id:'current', events:[event(1, 2)]}, {id:'empty', events:[]},
  ];
  const grouped = groupAlternatives(options, 'current');
  assert.deepEqual(grouped.same.map(item=>item.option.id), ['current','same']);
  assert.deepEqual(grouped.other.map(item=>item.option.id), ['other','empty']);
  assert.deepEqual(grouped.same.map(item=>item.index), [2,1]);
  assert.equal(groupAlternatives(options,'unknown').other.length,4);
  assert.equal(groupAlternatives(options,'empty').same.length,0);
});
