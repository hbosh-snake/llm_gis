# Sourced by the bin/* wrappers. Exports the invoking user's ids so the agent
# container runs as them and bind-mounted output stays owned by the caller.
# UID is readonly in bash and GID does not exist, hence the prefixed names.
export LLM_GIS_UID="$(id -u)"
export LLM_GIS_GID="$(id -g)"
