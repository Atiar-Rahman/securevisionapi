from threading import Lock

_last_suspicious_state = {}
_lock = Lock()


def should_send_suspicious_email(camera_id, suspicious):
    """Return True only when suspicious transitions from False to True.

    If suspicious stays True, this returns False.
    If suspicious becomes False, the state is reset so the next True will send again.
    If suspicious is None, the state remains unchanged.
    """
    if suspicious is None:
        return False

    with _lock:
        previous = _last_suspicious_state.get(camera_id, False)
        if suspicious:
            if not previous:
                _last_suspicious_state[camera_id] = True
                return True
            return False

        # normal or non-suspicious result resets the state
        _last_suspicious_state[camera_id] = False
        return False
