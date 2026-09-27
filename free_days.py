"""Whole-day occupancy is shared across courses, never summed per course."""


def teaching_weeks(catalog):
    weeks = {int(w) for c in catalog for o in c['options'] for e in o['events'] for w in e['weeks']}
    return list(range(min(weeks), max(weeks)+1)) if weeks else []


def occupied_days(events):
    return {(int(week), int(event['day'])) for event in events for week in event['weeks']}


def free_day_summary(catalog, events):
    weeks = teaching_weeks(catalog)
    occupied = occupied_days(events)
    rows = [dict(week=week, weekdays=[day for day in range(5) if (week,day) not in occupied],
                 weekends=[day for day in (5,6) if (week,day) not in occupied]) for week in weeks]
    free = sum(len(row['weekdays']) for row in rows)
    weekend_free = sum(len(row['weekends']) for row in rows)
    total = len(weeks)*5
    return dict(first_week=weeks[0] if weeks else None, last_week=weeks[-1] if weeks else None,
                week_count=len(weeks), weekday_free=free, weekend_free=weekend_free,
                weekday_occupied=total-free, average_free_weekdays=round(free/len(weeks),2) if weeks else 0,
                rows=rows)


def add_day_occupancy(catalog, variable_by_key, variables, objective, constraints, weight, expression):
    """Charge average occupied weekdays; multiple lessons on one day count once."""
    weeks = teaching_weeks(catalog)
    if not weight or not weeks:
        return
    occupants = {}
    for course in catalog:
        for option in course['options']:
            variable = variable_by_key[(course['id'],option['id'])]
            for week, day in occupied_days(option['events']):
                if day < 5:
                    occupants.setdefault((week,day),set()).add(variable)
    for (week,day), choices in sorted(occupants.items()):
        variable = f'occupied_w{week}_d{day}'
        variables.append(variable)
        objective.append((weight/len(weeks), variable))
        for choice in sorted(choices):
            constraints.append(f'day_has_{variable}_{choice}: {choice} - {variable} <= 0')
        terms = [(1,variable)]+[(-1,choice) for choice in sorted(choices)]
        constraints.append(f'day_only_{variable}: {expression(terms)} <= 0')
