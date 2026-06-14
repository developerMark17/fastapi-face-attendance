from app.services import websocket_manager
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
        
        is_other_present = len(self.rooms[student_code]) > 0
        self.rooms[student_code].add(websocket)
        
        await websocket.send_json({
            "type": "device_status",
            "status": "online" if is_other_present else "offline"
        })
        
        if is_other_present:
            for connection in self.rooms[student_code]:
                if connection != websocket:
                    try:
                        await connection.send_json({"type": "device_status", "status": "online"})
                        # Tell the phone to re-send offer so admin gets fresh stream
                        await websocket.send_json({"type": "join"})
                    except Exception:
                        pass

    async def disconnect(self, websocket: WebSocket, student_code: str):
        if student_code in self.rooms:
            self.rooms[student_code].discard(websocket)
            
            # Notify any remaining peers that we disconnected
            for connection in list(self.rooms[student_code]):
                try:
                    await connection.send_json({"type": "device_status", "status": "offline"})
                except Exception:
                    pass
            
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
