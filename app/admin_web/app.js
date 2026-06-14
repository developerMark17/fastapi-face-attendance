let localPeerConnection = null;
let signalingWebSocket = null;
let currentStreamCode = null;   // ← ADD THIS

function closeLiveStream() {
  const modal = document.getElementById("webrtc-modal");
  modal.classList.add("hidden");
  currentStreamCode = null;      // ← ADD THIS

  if (signalingWebSocket) {
    signalingWebSocket.close();
    signalingWebSocket = null;
  }
  if (localPeerConnection) {
    localPeerConnection.close();
    localPeerConnection = null;
  }
  const videoEl = document.getElementById("webrtc-video");
  if (videoEl) videoEl.srcObject = null;
}

// ← NEW: create a fresh PC and wire it to the existing WS
function createPeerConnection(statusEl, videoEl) {
  if (localPeerConnection) {
    localPeerConnection.close();
    localPeerConnection = null;
  }
  const pc = new RTCPeerConnection({
    iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
  });
  localPeerConnection = pc;

  pc.ontrack = event => {
    videoEl.srcObject = event.streams[0];
    statusEl.textContent = "● LIVE";
    statusEl.style.background = "#dc2626";
  };

  pc.onicecandidate = event => {
    if (event.candidate && signalingWebSocket?.readyState === WebSocket.OPEN) {
      signalingWebSocket.send(JSON.stringify({ type: "candidate", candidate: event.candidate }));
    }
  };

  // If connection drops, update status
  pc.onconnectionstatechange = () => {
    if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
      statusEl.textContent = "Device Offline (App Closed)";
      statusEl.style.background = "#dc2626";
      videoEl.srcObject = null;
    }
  };

  return pc;
}

async function showLiveStream(studentCode, studentName) {
  closeLiveStream();

  const modal = document.getElementById("webrtc-modal");
  const modalTitle = document.getElementById("webrtc-modal-title");
  const statusEl = document.getElementById("webrtc-status");
  const videoEl = document.getElementById("webrtc-video");

  modalTitle.textContent = `Live Stream: ${studentName}`;
  statusEl.textContent = "Connecting to signaling server...";
  statusEl.style.background = "rgba(0,0,0,0.6)";
  modal.classList.remove("hidden");
  currentStreamCode = studentCode;   // ← ADD THIS

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws/signaling/${studentCode}`;
  signalingWebSocket = new WebSocket(wsUrl);

  // Create initial PC
  let pc = createPeerConnection(statusEl, videoEl);

  signalingWebSocket.onopen = () => {
    statusEl.textContent = "Waiting for device to start streaming...";
    signalingWebSocket.send(JSON.stringify({ type: "join" }));
  };

  signalingWebSocket.onmessage = async event => {
    try {
      const message = JSON.parse(event.data);

      if (message.type === "device_status") {
        if (message.status === "offline") {
          statusEl.textContent = "Device Offline (App Closed)";
          statusEl.style.background = "#dc2626";
          videoEl.srcObject = null;
          // Reset PC so it's ready for when device reconnects
          pc = createPeerConnection(statusEl, videoEl);
        } else if (message.status === "online") {
          statusEl.textContent = "Device reconnected, connecting...";
          statusEl.style.background = "#eab308";
          // ← KEY FIX: fresh PC + re-trigger the offer flow
          pc = createPeerConnection(statusEl, videoEl);
          signalingWebSocket.send(JSON.stringify({ type: "join" }));
        }
      } else if (message.type === "offer") {
        statusEl.textContent = "Establishing connection...";
        await pc.setRemoteDescription(new RTCSessionDescription({ type: "offer", sdp: message.sdp }));
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        signalingWebSocket.send(JSON.stringify({ type: "answer", sdp: answer.sdp }));
      } else if (message.type === "candidate") {
        if (message.candidate) {
          await pc.addIceCandidate(new RTCIceCandidate(message.candidate));
        }
      }
    } catch (err) {
      console.error("Signaling error:", err);
    }
  };

  signalingWebSocket.onclose = () => {
    if (currentStreamCode) {   // modal still open — try to reconnect WS
      statusEl.textContent = "Reconnecting...";
      setTimeout(() => {
        if (currentStreamCode) showLiveStream(currentStreamCode, studentName);
      }, 3000);
    }
  };
}