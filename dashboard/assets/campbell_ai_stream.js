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
  });

  var PLACEHOLDER_ID = "campbell-ai-stream-placeholder";

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
      setPlaceholderText("");

      fetch("campbell-ai/stream", {
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

    /* Polled by a dcc.Interval; hands the parked payload to a dcc.Store once. */
    collect: function () {
      if (!state.result) {
        return window.dash_clientside.no_update;
      }
      var payload = state.result;
      state.result = null;
      state.controller = null;
      return payload;
    },
  };
})();
