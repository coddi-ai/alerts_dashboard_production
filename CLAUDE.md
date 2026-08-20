# Claude — Dashboard W34

Esta es una tarea aislada para implementar las mejoras del dashboard asignadas a Francisco Vilches durante 2026-W34.

Antes de editar:

1. Lee `documentation/general/PLAN_W34_DASHBOARD_CLAUDE.md` completo.
2. Lee `.coddi-local/task.json` y confirma que estás en la rama y worktree indicados allí.
3. Revisa `git status --short --branch`; la base esperada es `dev@506ad72f765198b32effa261f04e5319730c34bf`.

Reglas de trabajo:

- Puedes modificar cualquier archivo necesario dentro de este worktree para resolver el alcance del plan.
- No uses la copia productiva local, otros worktrees, `.env`, secretos, credenciales ni claves.
- No ejecutes `git push`, despliegues, Docker con servicios externos, AWS/S3 ni pipelines productivos sin aprobación explícita.
- Implementa por incrementos pequeños y conserva una matriz de trazabilidad por mejora.
- Ejecuta primero las validaciones offline; registra comandos y resultados en el handoff de la tarea.
- La integración a `dev` será revisada por la persona usuaria; no hagas merge ni cherry-pick.
