import { beforeEach, describe, expect, it, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

const getRuntimeToolDecisionSummaryMock = vi.fn()
const getRuntimeCheckpointSummaryMock = vi.fn()
const replayRuntimeTraceMock = vi.fn()

vi.mock("@/api/admin", () => ({
  adminApi: {
    getRuntimeToolDecisionSummary: getRuntimeToolDecisionSummaryMock,
    getRuntimeCheckpointSummary: getRuntimeCheckpointSummaryMock,
    replayRuntimeTrace: replayRuntimeTraceMock,
  },
}))

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe("runtime store", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it("deduplicates concurrent tool summary loads for the same filters", async () => {
    const deferred = createDeferred<{ total: number; matrix_by_tool: any[]; matrix_by_reason: any[]; trend_by_hour: any[] }>()
    getRuntimeToolDecisionSummaryMock.mockReturnValue(deferred.promise)

    const { useRuntimeStore } = await import("../runtime")
    const store = useRuntimeStore()

    const first = store.loadToolDecisionSummary()
    const second = store.loadToolDecisionSummary()

    expect(getRuntimeToolDecisionSummaryMock).toHaveBeenCalledTimes(1)

    deferred.resolve({
      total: 3,
      matrix_by_tool: [],
      matrix_by_reason: [],
      trend_by_hour: [],
    })

    await Promise.all([first, second])

    expect(store.toolDecisionSummary?.total).toBe(3)
  })

  it("reuses recent tool summary payload without refetching immediately", async () => {
    getRuntimeToolDecisionSummaryMock.mockResolvedValue({
      total: 1,
      matrix_by_tool: [],
      matrix_by_reason: [],
      trend_by_hour: [],
    })

    const { useRuntimeStore } = await import("../runtime")
    const store = useRuntimeStore()

    await store.loadToolDecisionSummary()
    await store.loadToolDecisionSummary()

    expect(getRuntimeToolDecisionSummaryMock).toHaveBeenCalledTimes(1)
  })

  it("deduplicates concurrent checkpoint summary loads for the same limit", async () => {
    const deferred = createDeferred<{ items: Array<{ session_id: string }> }>()
    getRuntimeCheckpointSummaryMock.mockReturnValue(deferred.promise)

    const { useRuntimeStore } = await import("../runtime")
    const store = useRuntimeStore()

    const first = store.loadCheckpointSummary(20)
    const second = store.loadCheckpointSummary(20)

    expect(getRuntimeCheckpointSummaryMock).toHaveBeenCalledTimes(1)

    deferred.resolve({ items: [{ session_id: "session-1" }] })

    await Promise.all([first, second])

    expect(store.checkpointSummary).toHaveLength(1)
  })
})
