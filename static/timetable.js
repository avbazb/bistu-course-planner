(function (root) {
  // 学期总览只把时间范围相连的事件放进同一组；上午的重叠不能压窄下午的卡片。
  function positionEvents(events, week = 0) {
    const valid = events.filter((event) =>
      Number.isInteger(event.day) && event.day >= 0 && event.day < 7 &&
      Number.isInteger(event.start) && Number.isInteger(event.end) &&
      event.start >= 1 && event.end <= 14 && event.end >= event.start &&
      Array.isArray(event.weeks) && event.weeks.length && (!week || event.weeks.includes(week))
    ).sort((a, b) => a.day - b.day || a.start - b.start || a.end - b.end || String(a.course_id).localeCompare(String(b.course_id)));
    const result = [];
    let group = [];
    let groupEnd = 0;
    function flush() {
      const laneEnds = [];
      const placed = group.map((event) => {
        let lane = laneEnds.findIndex((end) => end < event.start);
        if (lane < 0) lane = laneEnds.length;
        laneEnds[lane] = event.end;
        return { event, lane };
      });
      result.push(...placed.map((item) => ({ ...item, laneCount: laneEnds.length })));
      group = [];
      groupEnd = 0;
    }
    for (const event of valid) {
      if (group.length && (event.day !== group[0].day || event.start > groupEnd)) flush();
      group.push(event);
      groupEnd = Math.max(groupEnd, event.end);
    }
    flush();
    return result;
  }
  function scheduleSignature(events) {
    // 比较全学期实际占用的周/星期/节次，忽略教师、教室以及记录如何拆分。
    const slots = new Set();
    for (const event of events ?? []) {
      for (const week of event.weeks ?? []) {
        for (let period = event.start; period <= event.end; period += 1) {
          slots.add([week, event.day, period].join(":"));
        }
      }
    }
    return [...slots].sort().join("|");
  }
  function groupAlternatives(options, currentId) {
    const current = options.find((option) => option.id === currentId);
    const signature = current ? scheduleSignature(current.events) : null;
    const same = [], other = [];
    options.forEach((option, index) => {
      const item = { option, index, isCurrent: option.id === currentId };
      if (signature && scheduleSignature(option.events) === signature) same.push(item);
      else other.push(item);
    });
    same.sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent) || a.index - b.index);
    return { same, other };
  }
  function teacherText(item) { return item?.teacher || ""; }
  root.TimetableLayout = { positionEvents, scheduleSignature, groupAlternatives, teacherText };
  if (typeof module !== "undefined") module.exports = root.TimetableLayout;
})(globalThis);
