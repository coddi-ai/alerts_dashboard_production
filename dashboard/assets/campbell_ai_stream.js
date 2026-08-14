/*
 * Progressive rendering for Campbell AI answers.
 *
 * A Dash callback only returns once it finishes, so this script streams the text
 * itself and hands control back to Dash at the end:
 *
 *   1. a clientside callback starts the stream when a pending message appears;
 *   2. deltas are appended into a placeholder bubble as they arrive;
 *   3. the final payload is parked on `window.__campbellStream.result`, which a
 *      polling clientside callback lifts into a dcc.Store so the normal Dash
 *      render produces charts, feedback controls and canonical history.
 *
 * Any failure parks `{ok: false}` instead, and the server callback falls back to
 * the blocking request. A broken stream degrades; it never loses the question.
 */
(function () {
  "use strict";

  var namespace = (window.dash_clientside = window.dash_clientside || {});
  var state = (window.__campbellStream = {
    result: null,
    controller: null,
    requestId: 0,
    startedAt: 0,
    lastEventAt: 0,
    running: false,
    /*
     * Last whole second already reported by `progress()`. The interval ticks about three
     * times a second while `elapsed` only changes once, so this collapses the surplus
     * ticks into no_update instead of re-rendering the same string.
     */
    lastReportedElapsed: -1,
  });

  var PLACEHOLDER_ID = "campbell-ai-stream-placeholder";

  /*
   * A stream that goes quiet is the failure this watchdog exists for.
   *
   * `fetch` only rejects when the connection breaks. A connection that stays open
   * while the server sends nothing — a stalled worker, a proxy holding the socket —
   * leaves `pump()` waiting forever: nothing is parked, the polling callback keeps
   * returning no_update, and the composer that was disabled when the message was sent
   * is never re-enabled. The tab sits on "Pensando..." with no way out while the answer
   * completes server-side and is quietly persisted, which is exactly the "se pega, y al
   * refrescar ya estaba respondida" report.
   *
   * So prolonged silence is treated as a failure, and the answer is recovered through
   * the fallback path rather than waited on forever.
   */
  var STALL_TIMEOUT_MS = 45000;

  function streamUrl() {
    var path = window.location.pathname || "/";
    var marker = "/agents/campbell-ai";
    var index = path.indexOf(marker);
    var prefix = index >= 0 ? path.slice(0, index) : "";
    return (prefix || "") + "/campbell-ai/stream";
  }

  function setPlaceholderText(text) {
    var node = document.getElementById(PLACEHOLDER_ID);
    if (!node) {
      return;
    }
    node.textContent = text;
    var scroller = document.getElementById("campbell-ai-messages");
    if (scroller) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }

  function park(requestId, payload) {
    // Ignore a late event from a superseded request.
    if (requestId !== state.requestId) {
      return;
    }
    state.result = payload;
    state.running = false;
  }

  /* Any sign of life from the server, used by the stall watchdog. */
  function touch() {
    state.lastEventAt = Date.now();
  }

  function consume(response, onEvent) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder("utf-8");
    var buffer = "";

    function pump() {
      return reader.read().then(function (chunk) {
        if (chunk.done) {
          return null;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        var blocks = buffer.split("\n\n");
        buffer = blocks.pop();
        blocks.forEach(function (block) {
          var data = block
            .split("\n")
            .filter(function (line) {
              return line.indexOf("data:") === 0;
            })
            .map(function (line) {
              return line.slice(5).trim();
            })
            .join("");
          if (!data) {
            return;
          }
          try {
            onEvent(JSON.parse(data));
          } catch (error) {
            /* Skip a malformed frame; `done` or the fallback still resolves. */
          }
        });
        return pump();
      });
    }

    return pump();
  }

  namespace.campbellAiStream = {
    /* Fired when a pending message is created. Returns nothing to Dash. */
    start: function (pending) {
      if (!pending || !pending.message || !pending.stream) {
        return window.dash_clientside.no_update;
      }
      if (state.controller) {
        state.controller.abort();
      }
      var requestId = (state.requestId += 1);
      var controller = new AbortController();
      var text = "";
      var settled = false;
      state.controller = controller;
      state.result = null;
      state.startedAt = Date.now();
      state.running = true;
      /* Without this a second question would start at the previous one's second count
       * and report nothing until it happened to pass it. */
      state.lastReportedElapsed = -1;
      touch();
      setPlaceholderText("");

      fetch(streamUrl(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: pending.company_id,
          session_id: pending.session_id,
          message: pending.message,
        }),
        signal: controller.signal,
        credentials: "same-origin",
      })
        .then(function (response) {
          if (!response.ok || !response.body) {
            throw new Error("stream unavailable");
          }
          return consume(response, function (event) {
            touch();
            if (event.type === "delta") {
              text += event.text || "";
              setPlaceholderText(text);
            } else if (event.type === "status") {
              /* Tool progress matters: most of the wait happens before any text. */
              if (!text) {
                setPlaceholderText((event.detail || "Analizando") + "…");
              }
            } else if (event.type === "done") {
              settled = true;
              park(requestId, { ok: true, event: event });
            } else if (event.type === "error") {
              settled = true;
              park(requestId, { ok: false, detail: event.detail || "" });
            }
          });
        })
        .then(function () {
          if (!settled) {
            park(requestId, { ok: false, detail: "" });
          }
        })
        .catch(function (error) {
          if (!error || error.name !== "AbortError") {
            park(requestId, { ok: false, detail: "" });
          }
        });

      return window.dash_clientside.no_update;
    },

    /*
     * Polled by a dcc.Interval. Returns one of three things:
     *
     *   - the parked terminal payload, once;
     *   - a stall verdict, which is also terminal and starts the fallback;
     *   - no_update when there is nothing to hand over.
     *
     * Progress deliberately does NOT come through here. This store feeds a *server*
     * callback, and that callback declares the whole conversation as State - so every
     * progress tick used to upload the entire history for the server to answer with
     * no_update and a new status string. Roughly one wasted round trip per second for
     * the length of every answer, each one occupying a dashboard worker thread. The
     * counter is presentation and never needed the server; see `progress()`.
     *
     * The interval stays short precisely because this function is also what delivers the
     * finished answer: widening it would add that much dead time to the end of every
     * response, which is the one moment a user is watching.
     */
    collect: function () {
      if (!state.result && state.running) {
        var silentFor = Date.now() - state.lastEventAt;
        if (silentFor > STALL_TIMEOUT_MS) {
          /* The connection is open but dead. Give up on it so the fallback runs. */
          if (state.controller) {
            state.controller.abort();
          }
          state.running = false;
          state.controller = null;
          return { ok: false, detail: "", stalled: true };
        }
        return window.dash_clientside.no_update;
      }
      if (!state.result) {
        return window.dash_clientside.no_update;
      }
      var payload = state.result;
      state.result = null;
      state.controller = null;
      return payload;
    },

    /*
     * Report the wait, entirely in the browser.
     *
     * Returns [status text, status colour, panel open, panel text], or no_update for all
     * four when there is nothing new to say. Counting seconds and deciding that a wait
     * has become unreasonable are both pure functions of the clock and two numbers the
     * browser already holds, so none of it justifies a request.
     *
     * `slowAfterSeconds` is passed in from Python rather than duplicated here, so
     * SLOW_ANSWER_SECONDS stays defined once, in layout.py.
     */
    progress: function (waitingAck, slowAfterSeconds) {
      var nu = window.dash_clientside.no_update;
      var idle = [nu, nu, nu, nu];
      if (!state.running || state.result) {
        return idle;
      }
      var elapsed = Math.round((Date.now() - state.startedAt) / 1000);
      if (elapsed === state.lastReportedElapsed) {
        return idle;
      }
      state.lastReportedElapsed = elapsed;
      /*
       * `waitingAck` is how much extra time the user asked for by clicking "seguir
       * esperando", so it raises the bar rather than dismissing the panel permanently:
       * the panel reappears if the next stretch is also slow.
       */
      var threshold = (slowAfterSeconds || 0) + (waitingAck || 0);
      var show = elapsed >= threshold;
      return [
        "Pensando… " + elapsed + "s",
        "info",
        show,
        show ? "La consulta lleva " + elapsed + " segundos" : "",
      ];
    },

    /* Abort an in-flight stream because the user cancelled it. */
    stop: function () {
      if (state.controller) {
        state.controller.abort();
      }
      state.running = false;
      state.controller = null;
      state.result = null;
      state.requestId += 1;
      state.lastReportedElapsed = -1;
      return window.dash_clientside.no_update;
    },
  };
})();
