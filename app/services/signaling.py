from typing import Dict, Set
from fastapi import WebSocket


class SignalingManager:
    def __init__(self):
        # Maps student_code -> set of active WebSockets
        self.rooms: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, student_code: str):
        await websocket.accept()
        if student_code not in self.rooms:
            self.rooms[student_code] = set()
        self.rooms[student_code].add(websocket)

    def disconnect(self, websocket: WebSocket, student_code: str):
        if student_code in self.rooms:
            self.rooms[student_code].discard(websocket)
            if not self.rooms[student_code]:
                del self.rooms[student_code]

    async def send_message(self, message: dict, sender: WebSocket, student_code: str):
        if student_code in self.rooms:
            for connection in self.rooms[student_code]:
                if connection != sender:
                    try:
                        await connection.send_json(message)
                    except Exception:
                        # Will be cleaned up on disconnect or next broadcast attempt
                        pass


signaling_manager = SignalingManager()
