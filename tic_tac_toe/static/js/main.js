document.addEventListener("DOMContentLoaded", () => {
  const socket = io();

  // Global state from data attributes (if available)
  const body = document.body;
  const currentGameId = body.dataset.gameId || null;
  const playerSymbol = body.dataset.symbol || null;
  const currentUsername = body.dataset.username || null;

  let turnTimerInterval = null;
  let turnTime = 0;

  // ------------------------------
  // Dashboard Logic (if on dashboard)
  // ------------------------------
  const onlineUsersList = document.getElementById("users-list");
  if (onlineUsersList) {
    fetch("/online_users")
      .then((res) => res.json())
      .then((users) => {
        onlineUsersList.innerHTML = "";
        users.forEach((user) => {
          const li = document.createElement("li");
          li.innerHTML = `${user.username} <button class="send-challenge-btn" data-id="${user.id}">Challenge</button>`;
          onlineUsersList.appendChild(li);
        });
      });

    onlineUsersList.addEventListener("click", (e) => {
      if (e.target.classList.contains("send-challenge-btn")) {
        const opponentId = e.target.getAttribute("data-id");
        socket.emit("challenge", { to_user_id: parseInt(opponentId) });
        alert("Challenge sent!");
      }
    });
  }

  // ------------------------------
  // Challenge and Countdown Logic (Dashboard)
  // ------------------------------
  const challengePopup = document.getElementById("challenge-popup");
  if (challengePopup) {
    const challengeMessage = document.getElementById("challenge-message");
    const acceptBtn = document.getElementById("accept-challenge");
    const rejectBtn = document.getElementById("reject-challenge");
    let challengerId = null;

    socket.on("receive_challenge", (data) => {
      challengerId = data.from_user_id;
      challengeMessage.textContent = `${data.from_username} has challenged you!`;
      challengePopup.style.display = "flex";
    });

    acceptBtn.addEventListener("click", () => {
      challengePopup.style.display = "none";
      socket.emit("accept_challenge", { from_user_id: challengerId });
    });

    rejectBtn.addEventListener("click", () => {
      challengePopup.style.display = "none";
      challengerId = null;
    });

    socket.on("challenge_countdown", (data) => {
      challengeMessage.textContent = `Game begins in ${data.count} sec...`;
    });

    socket.on("game_start", (data) => {
      window.location.href = `/game/${data.game_id}`;
    });
  }

  // ------------------------------
  // Game Page Logic
  // ------------------------------
  if (currentGameId) {
    socket.emit("join", { game_id: currentGameId });

    // Board cell click handling.
    document.querySelectorAll(".cell").forEach((cell) => {
      cell.addEventListener("click", () => {
        const pos = parseInt(cell.dataset.cell);
        if (cell.textContent.trim() === "") {
          stopTurnTimer(); // Stop timer on move.
          fetch(`/move/${currentGameId}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ position: pos, symbol: playerSymbol }),
          })
            .then((res) => res.json())
            .then((data) => {
              if (data.error) {
                alert(data.error);
              }
            });
        }
      });
    });

    // Listen for game updates.
    socket.on("game_update", (data) => {
      if (parseInt(data.game_id) !== parseInt(currentGameId)) return;
      updateBoardUI(data.board);
      updateGameStatus(data.turn, data.winner);
      // If it's our turn and the game is ongoing, start the turn timer.
      if (!data.winner && data.turn === playerSymbol) {
        startTurnTimer();
      } else {
        stopTurnTimer();
      }
      // If the game is over, show result popup.
      if (data.winner) {
        let message = "";
        if (data.winner === "D") {
          message = "It's a draw!";
        } else {
          message = data.winner === playerSymbol ? "You win!" : "You lose!";
        }
        showResultPopup(message);
      }
    });
  }

  // ------------------------------
  // Chat Logic (for Game Page)
  // ------------------------------
  const chatForm = document.getElementById("chat-form");
  if (chatForm) {
    chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const chatInput = document.getElementById("chat-input");
      const message = chatInput.value.trim();
      if (message !== "") {
        socket.emit("chat_message", {
          game_id: currentGameId,
          message: message,
        });
        chatInput.value = "";
      }
    });
  }

  socket.on("chat_message", (data) => {
    appendChatMessage(data.username, data.message, data.timestamp);
  });

  socket.on("chat_history", (messages) => {
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
      chatBox.innerHTML = "";
      messages.forEach((msg) => {
        appendChatMessage(msg.username, msg.message, msg.timestamp);
      });
    }
  });

  // ------------------------------
  // Result Popup Logic (Game End)
  // ------------------------------
  const resultPopup = document.getElementById("result-popup");
  if (resultPopup) {
    const resultMessage = document.getElementById("result-message");
    const newGameBtn = document.getElementById("new-game");
    const leaveBtn = document.getElementById("leave-room");

    function showResultPopup(message) {
      resultMessage.textContent = message;
      resultPopup.style.display = "flex";
    }

    newGameBtn.addEventListener("click", () => {
      window.location.href = "/dashboard";
    });

    leaveBtn.addEventListener("click", () => {
      window.location.href = "/dashboard";
    });
  }

  // ------------------------------
  // Turn Timer Functions
  // ------------------------------
  const turnTimerDisplay = document.getElementById("turn-timer");
  function startTurnTimer() {
    turnTime = 0;
    if (turnTimerDisplay) {
      turnTimerDisplay.textContent = `Your turn: 0 sec`;
    }
    turnTimerInterval = setInterval(() => {
      turnTime++;
      if (turnTimerDisplay) {
        turnTimerDisplay.textContent = `Your turn: ${turnTime} sec`;
      }
    }, 1000);
  }

  function stopTurnTimer() {
    clearInterval(turnTimerInterval);
    turnTimerInterval = null;
    if (turnTimerDisplay) {
      turnTimerDisplay.textContent = "";
    }
  }

  // ------------------------------
  // Helper Functions
  // ------------------------------
  function updateBoardUI(board) {
    board.split("").forEach((cellVal, idx) => {
      const cell = document.querySelector(`[data-cell='${idx}']`);
      if (cell) cell.textContent = cellVal;
    });
  }

  function updateGameStatus(turn, winner) {
    const statusElem = document.getElementById("game-status");
    if (winner === "D") {
      statusElem.textContent = "It's a draw!";
    } else if (winner) {
      statusElem.textContent = `Player ${winner} wins!`;
    } else {
      statusElem.textContent = `Turn: ${turn}`;
    }
  }

  function appendChatMessage(username, message, timestamp) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;
    const msgElem = document.createElement("p");
    msgElem.innerHTML = `<strong>${username}</strong> <small>[${timestamp}]</small>: ${message}`;
    chatBox.appendChild(msgElem);
    chatBox.scrollTop = chatBox.scrollHeight;
  }
});
