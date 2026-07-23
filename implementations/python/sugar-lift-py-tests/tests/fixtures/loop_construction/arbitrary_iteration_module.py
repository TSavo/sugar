"""Source-structural semantic oracle for loop-construction acceptance."""


def continue_backedge():
    head = []
    tail = []
    post = 0
    for item in (0, 1, 2, 3):
        head.append(item)
        post = item + 1
        if item % 2 == 0:
            continue
        tail.append(item)
    return {"head": tuple(head), "tail": tuple(tail), "post": post}


def break_exit():
    visited = []
    completed_tail = []
    post = -1
    for item in (0, 1, 2, 3, 4):
        visited.append(item)
        post = item
        if item == 2:
            break
        completed_tail.append(item)
    return {
        "visited": tuple(visited),
        "completed_tail": tuple(completed_tail),
        "post": post,
    }


def for_else_exhaustion():
    events = []
    for item in (0, 1):
        events.append(f"body:{item}")
    else:
        events.append("else")
    return tuple(events)


def for_else_break():
    events = []
    for item in (0, 1, 2):
        events.append(f"body:{item}")
        if item == 1:
            break
    else:
        events.append("else")
    return tuple(events)


def while_else_exhaustion():
    events = []
    item = 0
    while item < 2:
        events.append(f"body:{item}")
        item += 1
    else:
        events.append("else")
    return tuple(events)


def while_else_break():
    events = []
    item = 0
    while item < 3:
        events.append(f"body:{item}")
        if item == 1:
            break
        item += 1
    else:
        events.append("else")
    return tuple(events)


def nested_break():
    events = []
    for outer in (0, 1):
        events.append(("outer", outer))
        for inner in (0, 1):
            events.append(("inner", outer, inner))
            break
        events.append(("after-inner", outer))
    events.append(("outer-complete",))
    return tuple(events)


def nested_continue():
    events = []
    for outer in (0, 1):
        for inner in (0, 1):
            events.append(("head", outer, inner))
            if inner == 0:
                continue
            events.append(("tail", outer, inner))
        events.append(("after-inner", outer))
    return tuple(events)


def concrete_bounded():
    trace = []
    state = 0
    for item in (1, 2, 3, 4):
        state += item
        trace.append((item - 1, state))
    return tuple(trace)


def symbolic_break(items, stop):
    visited = []
    stopped = False
    for item in items:
        visited.append(item)
        if item == stop:
            stopped = True
            break
    return {"visited": tuple(visited), "stopped": stopped}


def symbolic_break_lying(items, stop):
    result = symbolic_break(items, stop)
    assert result["visited"] == tuple(items)
    return result


def guarded_break_join(should_break):
    visited = []
    tail = []
    post = -1
    for item in (0, 1, 2):
        visited.append(item)
        post = item
        if should_break and item == 1:
            break
        tail.append(item)
    return {"visited": tuple(visited), "tail": tuple(tail), "post": post}


def guarded_continue_join(should_continue):
    visited = []
    tail = []
    post = 0
    for item in (0, 1, 2):
        visited.append(item)
        post = item + 1
        if should_continue and item == 1:
            continue
        tail.append(item)
    return {"visited": tuple(visited), "tail": tuple(tail), "post": post}
