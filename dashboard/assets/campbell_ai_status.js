/*
 * Estado visible mientras Campbell AI se inicializa.
 *
 * El badge nace con un texto fijo y solo cambia cuando el callback de servidor termina. Ese
 * callback hace una llamada HTTP bloqueante — dos al refrescar, porque la sesión sobrevive en
 * sessionStorage y entonces además se recupera el hilo — y un callback de Dash es atómico: no
 * puede emitir un valor intermedio. Durante toda la espera el texto no se mueve, y un texto
 * que no se mueve se lee como "se colgó".
 *
 * Todo lo que este archivo muestra es medido, nunca supuesto:
 *
 * - **La fase viene del servidor.** La API publica en qué paso está la llamada en vuelo y un
 *   callback de servidor la trae al store `campbell-ai-init-phase`. Cuando llega, el badge
 *   dice ese paso: "Leyendo datos", "Buscando conversación".
 * - **La etiqueta de respaldo es real.** Si el servidor no contesta, o contesta que no sabe
 *   nada, se usa un hecho conocido acá: si el navegador trae `session_id`, el trabajo incluye
 *   recuperar la conversación; si no, no.
 * - **El contador es real.** Es tiempo transcurrido, medido.
 *
 * Lo que no se hace, y es deliberado: una versión anterior cambiaba el texto a los 8 y a los
 * 25 segundos ("validando fuentes de datos", "esperando a la API") como si supiera dónde está
 * el servidor. No lo sabía: eran nombres inventados disparados por un reloj. De ahí la regla
 * de este archivo — si el paso no vino del servidor, no se nombra.
 */
(function () {
  var namespace = (window.dash_clientside = window.dash_clientside || {});

  /* `written` es el último texto que escribió este archivo, y es lo que define si el badge
   * sigue siendo nuestro. Reconocerlo por forma no sirve: el mismo badge muestra "Pensando…
   * 12s" y "Reintentando…" durante las respuestas, que también terminan en puntos
   * suspensivos. Y reconocerlo por nombre tampoco: las fases las nombra el servidor, así que
   * agregar una allá dejaría a este archivo creyendo que la inicialización terminó. */
  var state = { startedAt: 0, label: "", written: "" };

  /* El texto con que nace el badge en el layout. Es nuestro aunque no lo hayamos escrito
   * nosotros: es el estado con que arranca cada carga de página. */
  var INITIAL_TEXT = "Inicializando…";

  /* Antes de esto no se muestra el contador: un arranque rápido no necesita cronómetro, y
   * ponerlo desde el segundo cero convierte cualquier espera normal en algo que parece falla. */
  var COUNTER_AFTER = 4;

  /* Techo de seguridad. Si el badge sigue en progreso pasado esto, algo se perdió (un write
   * del servidor que no llegó, o un arranque que corrió después de que el servidor terminó) y
   * seguir contando para siempre sería mentir con más precisión. */
  var GIVE_UP_AFTER = 180;

  function labelFor(sessionId) {
    return sessionId ? "Recuperando" : "Inicializando";
  }

  /* Si el badge sigue mostrando lo último que pusimos, la inicialización sigue en curso.
   * Cualquier otro texto vino de otro callback — "Listo · CDA", "Pensando… 12s", un error —
   * y significa que este ciclo terminó. */
  function isOurs(text) {
    if (typeof text !== "string" || !text) return false;
    return text === state.written || text === INITIAL_TEXT;
  }

  /* La fase que informó el servidor, si informó alguna. */
  function serverLabel(phase) {
    if (!phase || typeof phase.label !== "string") return "";
    return phase.label;
  }

  function write(text) {
    state.written = text;
    return text;
  }

  namespace.campbellAiStatus = {
    /*
     * Arranca el ciclo, salvo que el badge ya muestre un estado final: Dash no garantiza el
     * orden entre este callback y el de servidor, y si el servidor gana la carrera, arrancar
     * el latido acá dejaría el badge contando para siempre sobre una sesión ya lista.
     */
    begin: function (_clientValue, sessionId, currentText) {
      var nu = window.dash_clientside.no_update;
      if (currentText && !isOurs(currentText)) {
        return [nu, nu, true];
      }
      state.startedAt = Date.now();
      state.label = labelFor(sessionId);
      return [write(state.label + "…"), "secondary", false];
    },

    /* Un tick por medio segundo: la fase que informó el servidor si la hay, la etiqueta de
     * respaldo si no, y los segundos cuando la espera se nota. */
    tick: function (_ticks, currentText, sessionId, phase) {
      var nu = window.dash_clientside.no_update;
      if (!isOurs(currentText)) {
        /* Otro callback ya escribió el badge; no lo pisamos. */
        return [nu, nu];
      }
      var elapsed = Math.round((Date.now() - state.startedAt) / 1000);
      var label = serverLabel(phase) || state.label || labelFor(sessionId);
      if (elapsed >= GIVE_UP_AFTER) {
        /* Se deja de contar y de reclamar el badge: a partir de acá es un estado final. */
        state.written = "";
        return ["Sin respuesta", "warning"];
      }
      if (elapsed < COUNTER_AFTER) {
        return [write(label + "…"), nu];
      }
      return [write(label + "… " + elapsed + "s"), nu];
    },

    /* Apaga el latido en cuanto el badge deja de ser nuestro. */
    settle: function (currentText) {
      return !isOurs(currentText);
    },
  };
})();
