from collections.abc import Sequence

import numpy as np

FACE_VECTOR_SIZE = 128


def has_valid_face_encoding(encoding: object) -> bool:
    if not isinstance(encoding, Sequence) or isinstance(encoding, (str, bytes)):
        return False
    if len(encoding) != FACE_VECTOR_SIZE:
        return False

    try:
        np.asarray(encoding, dtype=np.float64)
    except (TypeError, ValueError):
        return False

    return True


def compute_face_hash(encoding: Sequence[float] | np.ndarray, bits: int = 16) -> str:
    """Small deterministic bucket key used before exact face-distance matching.

    This is not a biometric identifier or a security boundary. It gives the
    database an indexed pre-filter so local deployments do not full-scan every
    stored embedding once student counts grow.
    """
    vector = np.asarray(encoding, dtype=np.float64)
    if vector.shape[0] < bits:
        bits = vector.shape[0]

    return "".join("1" if value >= 0 else "0" for value in vector[:bits])
