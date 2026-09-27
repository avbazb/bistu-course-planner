from __future__ import annotations
import math
import re
import time
from free_days import free_day_summary, add_day_occupancy
from solver_backends import solve_binary

def complete_option(option):
    return bool(option.get('events'))

DAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


SLOTS = [
    {"index": 1, "start": "08:00", "end": "08:45"},
    {"index": 2, "start": "08:50", "end": "09:35"},
    {"index": 3, "start": "09:50", "end": "10:35"},
    {"index": 4, "start": "10:40", "end": "11:25"},
    {"index": 5, "start": "11:30", "end": "12:15"},
    {"index": 6, "start": "13:30", "end": "14:15"},
    {"index": 7, "start": "14:20", "end": "15:05"},
    {"index": 8, "start": "15:20", "end": "16:05"},
    {"index": 9, "start": "16:10", "end": "16:55"},
    {"index": 10, "start": "17:00", "end": "17:45"},
    {"index": 11, "start": "18:30", "end": "19:15"},
    {"index": 12, "start": "19:20", "end": "20:05"},
    {"index": 13, "start": "20:10", "end": "20:55"},
    {"index": 14, "start": "21:00", "end": "21:45"},
]


DEFAULT_WEIGHTS = {
    "freeDays": 0.0,
    "early8": 5.0,
    "afternoonFirst": 0.0,
    "mondayMorning": 3.0,
    "fridayMorning": 0.0,
    "fridayAfternoon": 2.0,
    "fridayEvening": 2.0,
}


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def parse_week_expression(expression: str) -> tuple[list[int], str]:
    expression = expression.strip().replace("（", "(").replace("）", ")")
    parity = "all"
    if "双" in expression:
        parity = "even"
    elif "单" in expression:
        parity = "odd"
    expression = expression.replace("周", "").replace("、", ",").replace("，", ",")
    expression = re.sub(r"[()单双]", "", expression)
    expression = re.sub(r"\s*[-—–]\s*", "-", expression)
    weeks: set[int] = set()
    for token in re.split(r"[,\s]+", expression):
        token = token.strip()
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*[-—–]\s*(\d+)", token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                start, end = end, start
            weeks.update(range(start, end + 1))
        elif token.isdigit():
            weeks.add(int(token))
        else:
            raise ValueError(f"无法识别上课周数：{expression}")
    if not weeks or any(week < 1 or week > 53 for week in weeks):
        raise ValueError(f"无效上课周数：{expression}")
    if parity == "even":
        weeks = {week for week in weeks if week % 2 == 0}
    elif parity == "odd":
        weeks = {week for week in weeks if week % 2 == 1}
    # 单双周过滤后为空时不能回退成全学期，否则会制造并不存在的冲突。
    return sorted(weeks), parity


def option_penalties(events: list[dict]) -> dict[str, int]:
    penalties = {key: 0 for key in DEFAULT_WEIGHTS}
    for event in events:
        periods = set(range(event["start"], event["end"] + 1))
        if periods & {1, 2}:
            penalties["early8"] += 1
        if 6 in periods:
            penalties["afternoonFirst"] += 1
        if event["day"] == 0 and periods & set(range(1, 6)):
            penalties["mondayMorning"] += 1
        if event["day"] == 4 and periods & set(range(1, 6)):
            penalties["fridayMorning"] += 1
        if event["day"] == 4 and periods & set(range(6, 11)):
            penalties["fridayAfternoon"] += 1
        if event["day"] == 4 and periods & set(range(11, 15)):
            penalties["fridayEvening"] += 1
    return penalties


def event_key(event: dict) -> tuple:
    return (
        event["day"], event["start"], event["end"], tuple(event["weeks"]),
        event["teacher"], event["room"], event["parity"],
    )


def event_conflict(left: dict, right: dict) -> bool:
    if left["day"] != right["day"]:
        return False
    if left["end"] < right["start"] or right["end"] < left["start"]:
        return False
    return bool(set(left["weeks"]) & set(right["weeks"]))


def summarize_option(events: list[dict]) -> str:
    if not events:
        return "无固定课表"
    groups = []
    for event in sorted(events, key=lambda item: (item["day"], item["start"], item["end"])):
        place = event["room"] or "教室待定"
        who = event["teacher"] or "教师待定"
        groups.append(
            f"{DAYS[event['day']]} {event['start']}-{event['end']}节 "
            f"{event['weeks_text']} {who} {place}"
        )
    return "；".join(groups)


def teaching_class_capacity(teaching_class: dict) -> int | None:
    # HAR 的 classCapacity / KRL 表示总容量；YXRS 是已选人数，不用于这里。
    # 未提供数值与真实的 0 人容量必须区分。
    for key in ("classCapacity", "KRL"):
        raw = teaching_class.get(key)
        if raw is None or isinstance(raw, bool) or (isinstance(raw, str) and not raw.strip()):
            continue
        try:
            value = float(raw)
        except (ValueError, TypeError):
            continue
        if math.isfinite(value) and value >= 0 and value.is_integer():
            return int(value)
    return None


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value)
    return cleaned or "v"


def lp_number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.8g}"


def lp_expression(terms: list[tuple[float, str]]) -> str:
    pieces = []
    for coefficient, variable in terms:
        if abs(coefficient) < 1e-12:
            continue
        sign = "+" if coefficient >= 0 else "-"
        magnitude = lp_number(abs(coefficient))
        if not pieces:
            pieces.append(f"{'' if coefficient >= 0 else '-'} {magnitude} {variable}")
        else:
            pieces.append(f" {sign} {magnitude} {variable}")
    return "".join(pieces) or "0"


def format_constraint(terms: list[str], relation: str, rhs: int | float) -> str:
    return " + ".join(terms) + f" {relation} {lp_number(float(rhs))}"


def validate_solution(catalog, solution):
    """Validate the chosen catalog records, not client-supplied event copies."""
    chosen, self_study = {}, []
    assignments = solution.get('assignments', {})
    if not isinstance(assignments, dict) or set(assignments) != {c['id'] for c in catalog}:
        raise ValueError('课表课程与当前课程清单不一致')
    for course in catalog:
        assignment = assignments.get(course['id'], {})
        if not isinstance(assignment, dict):
            raise ValueError('课表班次格式无效')
        if assignment.get('kind') == 'self-study':
            if assignment.get('option_id') != 'self-study':
                raise ValueError('自主修读班次格式无效')
            if not solution.get('allow_self_study'):
                raise ValueError('当前未开启自主修读')
            self_study.append(course)
        elif course['options']:
            if assignment.get('kind') != 'option':
                raise ValueError('请选择有效的课程班次')
            option = next((o for o in course['options'] if o['id'] == assignment.get('option_id')), None)
            if not option or not complete_option(option):
                raise ValueError(f"{course['name']} 的上课时间不完整")
            chosen[course['id']] = option
        elif assignment.get('kind') != 'unassigned' or assignment.get('option_id') is not None:
            raise ValueError('无课表课程的状态无效')
    if len(self_study) > 2:
        raise ValueError('最多只能选择两门自主修读课程')
    items = list(chosen.items())
    for index, (code, option) in enumerate(items):
        for other_code, other in items[index+1:]:
            if any(event_conflict(a, b) for a in option['events'] for b in other['events']):
                raise ValueError(f'{code} 与 {other_code} 上课时间冲突')
    for course in self_study:
        if not course['options'] or any(not complete_option(o) for o in course['options']):
            raise ValueError(f"{course['name']} 班级时间不完整，不能判定全部冲突")
        for option in course['options']:
            if not any(event_conflict(a, b) for a in option['events']
                       for other in chosen.values() for b in other['events']):
                raise ValueError(f"{course['name']} 仍有无冲突班级，不能自主修读")


def solve(catalog: list[dict], request: dict, *, backend="ortools") -> dict:
    if not isinstance(request, dict):
        raise ValueError("排课参数必须是对象")
    if not isinstance(request.get("weights", {}), dict):
        raise ValueError("权重参数必须是对象")
    weights = dict(DEFAULT_WEIGHTS)
    for key in weights:
        try:
            value = float(request.get("weights", {}).get(key, weights[key]))
        except (TypeError, ValueError):
            raise ValueError("权重必须是 0 到 10 的数字")
        if not math.isfinite(value) or not 0 <= value <= 10:
            raise ValueError("权重必须是 0 到 10 的数字")
        weights[key] = value
    allow_self_study = request.get("allow_self_study", False)
    if not isinstance(allow_self_study, bool):
        raise ValueError("自主学习开关必须为布尔值")
    if not isinstance(request.get("fixed", {}), dict):
        raise ValueError("班次参数必须是对象")
    fixed = request.get("fixed", {}) if isinstance(request.get("fixed", {}), dict) else {}
    if any(not isinstance(value, str) for value in fixed.values()):
        raise ValueError("请选择有效班次")
    previous = request.get("previous", {}) if isinstance(request.get("previous", {}), dict) else {}
    if set(fixed) - {course['id'] for course in catalog}:
        raise ValueError("课程清单已变化，请刷新后重新选择")
    if sum(choice == "self-study" for choice in fixed.values()) > 2:
        raise ValueError("最多只能选择两门自主学习课程")
    if not allow_self_study and "self-study" in fixed.values():
        raise ValueError("请先开启允许自主学习")
    # 大于所有普通班次目标代价之和，确保先尽量少用自主学习，再优化各项偏好。
    self_study_penalty = 1.0 + sum(
        max((sum(weights[key] * option['penalties'].get(key,0) for key in weights if key != 'freeDays')
             + 0.05 + index * 0.00001 for index, option in enumerate(course['options'])), default=0.05)
        for course in catalog
    ) + 5 * weights['freeDays']
    variable_by_key: dict[tuple[str, str], str] = {}
    variables: list[str] = []
    course_variables: dict[str, list[str]] = {}
    objective_terms: list[tuple[float, str]] = []

    for course_index, course in enumerate(catalog):
        choices = []
        for option_index, option in enumerate(course["options"]):
            variable = f"x_{course_index}_{option_index}"
            variable_by_key[(course["id"], option["id"])] = variable
            variables.append(variable)
            choices.append(variable)
            penalty = sum(weights[key] * option["penalties"].get(key,0) for key in weights if key != 'freeDays')
            if previous.get(course["id"]) not in (None, option["id"]):
                penalty += 0.05
            objective_terms.append((penalty + option_index * 0.00001, variable))
        if allow_self_study and (course["options"] or fixed.get(course["id"]) == "self-study"):
            variable = f"y_{course_index}"
            variable_by_key[(course["id"], "self-study")] = variable
            variables.append(variable)
            choices.append(variable)
            self_penalty = self_study_penalty
            if previous.get(course["id"]) not in (None, "self-study"):
                self_penalty += 0.05
            objective_terms.append((self_penalty, variable))
        if not course["options"]:
            variable = f"z_{course_index}"
            variable_by_key[(course["id"], "unassigned")] = variable
            variables.append(variable)
            choices.append(variable)
            objective_terms.append((0.0, variable))
        course_variables[course["id"]] = choices

    constraints: list[str] = []
    add_day_occupancy(catalog, variable_by_key, variables, objective_terms, constraints, weights['freeDays'], lp_expression)
    # Reject malformed known sessions; unavailable lab sessions require manual checking.
    for course in catalog:
        for option in course['options']:
            if not complete_option(option):
                variable = variable_by_key[(course['id'], option['id'])]
                constraints.append(f"incomplete_{variable}: {variable} = 0")
    for course in catalog:
        choices = course_variables[course["id"]]
        if choices:
            constraints.append(f"choose_{safe_name(course['id'])}: {format_constraint(choices, '=', 1)}")

    if allow_self_study:
        self_vars = [variable for (course_id, choice), variable in variable_by_key.items() if choice == "self-study"]
        if self_vars:
            constraints.append(f"self_study_limit: {format_constraint(self_vars, '<=', 2)}")

    blockers = {variable: set() for variable in variables}
    for left_index, left in enumerate(catalog):
        for right in catalog[left_index + 1 :]:
            for left_option in left["options"]:
                left_var = variable_by_key.get((left["id"], left_option["id"]))
                if not left_var:
                    continue
                for right_option in right["options"]:
                    if not any(
                        event_conflict(left_event, right_event)
                        for left_event in left_option["events"]
                        for right_event in right_option["events"]
                    ):
                        continue
                    right_var = variable_by_key.get((right["id"], right_option["id"]))
                    if right_var:
                        blockers[left_var].add(right_var)
                        blockers[right_var].add(left_var)
                        constraints.append(
                            f"conf_{left_index}_{left_option['id']}_{right_option['id']}: "
                            f"{format_constraint([left_var, right_var], '<=', 1)}"
                        )

    # A high penalty alone does not protect a manually fixed self-study choice.
    # Every class of this course must be blocked by an actually selected class.
    if allow_self_study:
        for course in catalog:
            self_var = variable_by_key.get((course['id'], 'self-study'))
            if not self_var:
                continue
            if not course['options'] or any(not complete_option(o) for o in course['options']):
                constraints.append(f"self_unknown_{self_var}: {self_var} = 0")
            for option in course['options']:
                variable = variable_by_key[(course['id'], option['id'])]
                terms = [(1, self_var)] + [(-1, v) for v in sorted(blockers[variable])]
                constraints.append(f"self_blocked_{variable}: {lp_expression(terms)} <= 0")

    for course in catalog:
        selected = fixed.get(course["id"], "auto")
        if selected == "auto":
            continue
        if selected == "self-study":
            variable = variable_by_key.get((course["id"], "self-study"))
            if not variable:
                raise ValueError(f"{course['name']} 没有可自主学习的课表选项")
            constraints.append(f"fixed_{safe_name(course['id'])}: {format_constraint([variable], '=', 1)}")
        else:
            variable = variable_by_key.get((course["id"], selected))
            if not variable:
                raise ValueError(f"{course['name']} 的班次不存在")
            constraints.append(f"fixed_{safe_name(course['id'])}: {format_constraint([variable], '=', 1)}")

    if not variables:
        raise ValueError("没有可求解的课程变量")

    values, optimal, elapsed_ms = solve_binary(variables, objective_terms, constraints, backend)

    assignments = {}
    events = []
    self_study_count = 0
    unassigned_count = 0
    score = 0.0
    dimension_counts = {key: 0 for key in DEFAULT_WEIGHTS}
    for course in catalog:
        self_variable = variable_by_key.get((course["id"], "self-study"))
        if self_variable and values.get(self_variable, 0.0) > 0.5:
            assignments[course["id"]] = {
                "kind": "self-study",
                "label": "自主学习",
                "option_id": "self-study",
                "events": [],
            }
            self_study_count += 1
            score += self_study_penalty
            continue
        if not course["options"]:
            assignments[course["id"]] = {
                "kind": "unassigned",
                "label": "无课表记录",
                "option_id": None,
                "events": [],
            }
            unassigned_count += 1
            continue
        chosen_option = None
        for option in course["options"]:
            variable = variable_by_key[(course["id"], option["id"])]
            if values.get(variable, 0.0) > 0.5:
                chosen_option = option
                break
        if chosen_option is not None:
            assignments[course["id"]] = {
                "kind": "option",
                "label": chosen_option["label"],
                "option_id": chosen_option["id"],
                "events": chosen_option["events"],
            }
            for key in dimension_counts:
                if key == 'freeDays':
                    continue
                dimension_counts[key] += chosen_option["penalties"].get(key,0)
                score += weights[key] * chosen_option["penalties"].get(key,0)
            for event in chosen_option["events"]:
                events.append({
                    **event,
                    "course_id": course["id"],
                    "course_code": course["code"],
                    "course_name": course["name"],
                })
        else:
            assignments[course["id"]] = {
                "kind": "unassigned",
                "label": "未求得班次",
                "option_id": None,
                "events": [],
            }
            unassigned_count += 1

    day_off = free_day_summary(catalog, events)
    score += weights['freeDays'] * day_off['weekday_occupied'] / max(1,day_off['week_count'])
    dimension_counts['freeDays'] = day_off['weekday_free']
    solution = {
        "status": "optimal" if optimal else "feasible",
        "assignments": assignments,
        "events": events,
        "weights": weights,
        "allow_self_study": allow_self_study,
        "self_study_count": self_study_count,
        "unassigned_count": unassigned_count,
        "scheduled_count": len(catalog) - self_study_count - unassigned_count,
        "dimension_counts": dimension_counts,
        "objective": round(score, 4),
        "elapsed_ms": elapsed_ms,
        "solver": backend,
        "day_off": day_off,
    }
    validate_solution(catalog, solution)
    return solution
