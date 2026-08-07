# Study notes — Stateful Agentic Orchestrator

Reference material, carried over from `projects-ref.md`.

## References

### [`khoj-ai/khoj`](https://github.com/khoj-ai/khoj)

A fantastic open-source AI backend built heavily on FastAPI and asynchronous Python.

**What to study:** how they handle **WebSocket connections to stream tokens back to a client while a
long-running agentic loop is thinking in the background.** That's precisely the problem this repo
solves, so read their connection handling closely:

- How the async task running the agent is decoupled from the socket handler
- What happens to in-flight work when the client disconnects
- How they avoid blocking the event loop during LLM calls

Note what they *don't* solve that this repo must: khoj's model is largely single-instance. The
cross-instance event routing (M5 here) is the addition, and knowing that boundary is what lets you say
"I went further than the reference" credibly.

### [`langchain-ai/langgraph`](https://github.com/langchain-ai/langgraph)

The standard for agent state machines.

**What to study:** how **"State" is passed from node to node as a simple Python dictionary.** The design
insight worth stealing is that state is *plain serializable data* — which is exactly what makes runs
checkpointable, resumable, and inspectable.

Also read their **checkpointer** interface. They persist state after each node so a run can be resumed
or time-travelled. That's the model for M2 and M6 here — study the Postgres checkpointer implementation
specifically, since this repo uses PostgreSQL for the same job.

## Also worth reading

- **FastAPI WebSocket docs** and the underlying Starlette handling — particularly around cleanup on
  disconnect and why blocking the event loop kills every connection on the instance, not just one.
- **SQS visibility timeout** semantics. If a step takes longer than the timeout, the message is
  redelivered and the step runs twice. Tune it, and make steps idempotent anyway.
- **Redis pub/sub vs. streams.** Pub/sub is fire-and-forget: a subscriber that isn't connected misses
  the message. That's acceptable *because* PostgreSQL holds the durable sequence and replay comes from
  there — but be able to explain that division of responsibility, and know when Redis Streams would be
  the better call.

## Questions to answer before coding

1. A client's WebSocket is on instance A; the worker executing its run is on instance C. How does an
   event get from C to that client? What breaks if you skip pub/sub?
2. Client disconnects at step 4 of 10 and reconnects at step 7. How does it learn what happened in 5–6?
3. What guarantees no gaps *and* no duplicates in the replayed sequence?
4. What exactly is in a checkpoint, and what must *not* be (open handles, live object references)?
5. Worker dies mid-step. Does the step re-run? Is that safe? What makes it safe?
6. Where's the actual scaling ceiling — sockets per instance, DB connections, or LLM concurrency?

## Trap to avoid

Building and load-testing on a single instance. Everything works: the connection and the work share a
process, so events "just arrive." Then you deploy two ECS tasks and half the events vanish. Get to
multi-instance (M5) before believing any number.

## Deliberate divergences from the references

| Area | khoj / langgraph does | This repo does | Why |
| --- | --- | --- | --- |
| | | | |
