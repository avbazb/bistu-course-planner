(function (root) {
  const SCALE = 3;
  function wrapText(context, value, width) {
    const lines = [];
    for (const paragraph of String(value ?? "").split("\n")) {
      let line = "";
      for (const character of paragraph) {
        if (line && context.measureText(line + character).width > width) {
          lines.push(line);
          line = "";
        }
        line += character;
      }
      if (line) lines.push(line);
    }
    return lines;
  }
  async function render(snapshot) {
    await document.fonts.ready;
    const style = getComputedStyle(document.documentElement);
    const color = name => style.getPropertyValue(name).trim();
    const font = (size, bold = false) => (bold ? "600 " : "400 ") + size + 'px "Microsoft YaHei", "Segoe UI", sans-serif';
    const margin = 32, timeWidth = 96, headerY = 104, headerHeight = 48;
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) throw new Error("当前浏览器无法生成图片");
    const positioned = TimetableLayout.positionEvents(snapshot.solution.events, snapshot.week);
    // 导出不受屏幕宽度约束：并排课程保留可读宽度，周末空列适当收窄。
    const laneMax = snapshot.days.map((_, day) => Math.max(0, ...positioned.filter(item => item.event.day === day).map(item => item.laneCount)));
    const dayWidths = laneMax.map(lanes => lanes ? Math.max(224, lanes * 184) : 144);
    const width = Math.max(1800, margin * 2 + timeWidth + dayWidths.reduce((a, b) => a + b, 0));
    const extra = (width - margin * 2 - timeWidth - dayWidths.reduce((a, b) => a + b, 0)) / 7;
    dayWidths.forEach((value, index) => { dayWidths[index] = value + extra; });
    const dayX = [margin + timeWidth];
    dayWidths.forEach(value => dayX.push(dayX[dayX.length - 1] + value));
    const heights = Array(14).fill(96);
    const cards = positioned.map(({ event, lane, laneCount }) => {
      const index = snapshot.catalog.findIndex(course => course.id === event.course_id);
      const course = snapshot.catalog[index];
      const optionIndex = course.options.findIndex(option => option.id === snapshot.solution.assignments[course.id].option_id);
      const option = course.options[optionIndex];
      const cardWidth = dayWidths[event.day] / laneCount - 8;
      const blocks = [
        [event.course_name, 20, true],
        [course.code + (option.class_number ? " · " + option.class_number : " · 班次 " + (optionIndex + 1)), 14],
        [event.weeks_text + " · " + event.start + "-" + event.end + "节", 16],
        [TimetableLayout.teacherText(event), 16], [event.room, 16],
        [Number.isInteger(option.capacity) ? "总容量 " + option.capacity + " 人" : "", 14],
      ].filter(([value]) => value).map(([value, size, bold]) => {
        context.font = font(size, bold);
        return {lines:wrapText(context, value, cardWidth - 24),size,bold};
      });
      const textHeight = blocks.reduce((sum, block) => sum + block.lines.length * (block.size + 8) + 4, 0);
      // 单节、长课程名和同时间并排的课程都扩展行高，不省略文本。
      const required = textHeight + 32;
      const available = heights.slice(event.start - 1, event.end).reduce((a, b) => a + b, 0) - 8;
      if (required > available) {
        const extra = Math.ceil((required - available) / (event.end - event.start + 1));
        for (let i = event.start - 1; i < event.end; i++) heights[i] += extra;
      }
      return {event, lane, laneCount, index, blocks, textHeight, cardWidth};
    });
    const rowY = [headerY + headerHeight];
    heights.forEach(height => rowY.push(rowY[rowY.length - 1] + height));
    const offGrid = [["self-study", "自主学习"], ["unassigned", "无课表记录"]].map(([kind, label]) => ({
      label, names:snapshot.catalog.filter(course => snapshot.solution.assignments[course.id]?.kind === kind).map(course => course.name),
    })).filter(group => group.names.length);
    context.font = font(16);
    offGrid.forEach(group => { group.lines = wrapText(context, group.label + "：" + group.names.join("、"), width - margin * 2); });
    const height = rowY[14] + 32 + offGrid.reduce((sum, group) => sum + group.lines.length * 24 + 16, 0);
    if (width * height * SCALE * SCALE > 90_000_000) throw new Error("课表过大，请切换到单周后导出");
    canvas.width = width * SCALE;
    canvas.height = height * SCALE;
    context.scale(SCALE, SCALE);
    context.fillStyle = color("--color-neutral-0");
    context.fillRect(0, 0, width, height);
    context.textBaseline = "top";
    context.fillStyle = color("--color-neutral-900");
    context.font = font(24, true);
    context.fillText(snapshot.week ? "第 " + snapshot.week + " 周课表" : "学期课表", margin, 24);
    context.font = font(16);
    context.fillStyle = color("--color-neutral-500");
    context.fillText("2026—2027 第一学期", margin, 64);
    context.lineWidth = 1;
    const cell = (x, y, w, h, fill) => {
      context.fillStyle = fill;
      context.fillRect(x, y, w, h);
      context.strokeStyle = color("--color-neutral-200");
      context.strokeRect(x, y, w, h);
    };
    const centered = (text, x, y, w, size = 16) => {
      context.font = font(size, true);
      context.fillStyle = color("--color-neutral-700");
      context.fillText(text, x + (w - context.measureText(text).width) / 2, y);
    };
    cell(margin, headerY, timeWidth, headerHeight, color("--color-neutral-100"));
    centered("节次", margin, headerY + 12, timeWidth);
    snapshot.days.forEach((day, index) => {
      const x = dayX[index], dayWidth = dayWidths[index];
      cell(x, headerY, dayWidth, headerHeight, color("--color-neutral-100"));
      centered(day, x, headerY + 12, dayWidth);
    });
    snapshot.slots.forEach((slot, index) => {
      const y = rowY[index], h = heights[index];
      cell(margin, y, timeWidth, h, color("--color-neutral-50"));
      centered(String(slot.index), margin, y + h / 2 - 32, timeWidth);
      centered(slot.start, margin, y + h / 2 - 4, timeWidth, 14);
      centered(slot.end, margin, y + h / 2 + 20, timeWidth, 14);
      for (let day = 0; day < 7; day++) cell(dayX[day], y, dayWidths[day], h, color(day > 4 ? "--color-neutral-50" : "--color-neutral-0"));
      if ([6, 11].includes(slot.index)) {
        context.fillStyle = color("--color-neutral-300");
        context.fillRect(margin, y, width - margin * 2, 2);
      }
    });
    cards.forEach(({event,lane,laneCount,index,blocks,textHeight,cardWidth}) => {
      const x = dayX[event.day] + lane * dayWidths[event.day] / laneCount + 4;
      const y = rowY[event.start - 1] + 4, h = rowY[event.end] - y - 4;
      context.fillStyle = color("--course-" + (index % 8) + "-bg");
      context.beginPath();
      context.roundRect(x, y, cardWidth, h, 6);
      context.fill();
      context.fillStyle = color("--course-" + (index % 8) + "-border");
      context.fillRect(x, y + 4, 4, h - 8);
      context.fillStyle = color("--course-" + (index % 8) + "-text");
      let textY = y + Math.max(12, (h - textHeight) / 2);
      blocks.forEach(block => {
        context.font = font(block.size, block.bold);
        block.lines.forEach(line => { context.fillText(line, x + 12, textY); textY += block.size + 8; });
        textY += 4;
      });
    });
    if (!cards.length) {
      context.fillStyle = color("--color-neutral-500");
      context.font = font(20);
      context.fillText("本周没有已排课程", margin + timeWidth + 24, rowY[0] + 32);
    }
    context.font = font(16);
    context.fillStyle = color("--color-neutral-700");
    let footerY = rowY[14] + 24;
    offGrid.forEach(group => {
      group.lines.forEach(line => { context.fillText(line, margin, footerY); footerY += 24; });
      footerY += 16;
    });
    const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("图片生成失败，请重试");
    return {blob, width:canvas.width, height:canvas.height};
  }
  function save(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  function base64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(new Error("无法读取课表图片"));
      reader.readAsDataURL(blob);
    });
  }
  async function download(snapshot, format) {
    const rendered = await render(snapshot);
    const name = "北信科课表-" + (snapshot.week ? "第" + snapshot.week + "周" : "学期总览");
    if (format === "png") { save(rendered.blob, name + ".png"); return; }
    const response = await fetch("/api/export/xlsx", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        assignments:Object.fromEntries(Object.entries(snapshot.solution.assignments).map(([id, assignment]) => [id, assignment.option_id])),
        week:snapshot.week, image:await base64(rendered.blob),
      }),
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.error || "Excel 导出失败");
    }
    save(await response.blob(), name + ".xlsx");
  }
  root.TimetableExport = {render,download};
})(globalThis);
