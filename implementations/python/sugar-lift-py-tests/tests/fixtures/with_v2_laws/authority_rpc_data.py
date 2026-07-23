def write(value):
    return {"z9": value}


def read(message):
    return message["z9"]


ordinary = read(write({"x": 1}))
