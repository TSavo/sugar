def read_after_store(receiver, supplied):
    receiver.payload = supplied
    return receiver.payload


def renamed_read_after_store(container, offered):
    container.marker = offered
    return container.marker
