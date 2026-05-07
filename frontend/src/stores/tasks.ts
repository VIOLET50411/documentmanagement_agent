import { defineStore } from "pinia"
import { ref } from "vue"
import { adminApi } from "@/api/admin"

export interface RuntimeTask {
  task_id: string
  type: string
  status: string
  description?: string
  trace_id?: string
  retries?: number
  start_time?: string
  end_time?: string
  updated_at?: string
  stage?: string
}

export interface PipelineJob {
  doc_id: string
  title?: string
  status: string
  percentage?: number
  attempt?: number
  detail?: string
  error_message?: string
  updated_at?: string
  task_id?: string
}

export interface TrainingJob {
  id: string
  target_model_name?: string
  dataset_name?: string
  status: string
  stage?: string
  provider?: string
  train_records?: number
  val_records?: number
  error_message?: string
  updated_at?: string
  created_at?: string
  runtime_task_id?: string
}

export interface CheckpointSummary {
  session_id: string
  latest_node_name?: string
  latest_iteration?: number
  resumable: boolean
  latest_at?: string
}

export interface TraceEvent {
  event_id?: string
  sequence_num?: number
  status?: string
  type?: string
  source?: string
  trace_id?: string
  fallback_reason?: string
  message?: string
  msg?: string
  answer?: string
  content?: string
  timestamp?: string
  created_at?: string
  degraded?: boolean
}

export const useTasksStore = defineStore("tasks", () => {
  const loading = ref(false)
  const error = ref("")
  const runtimeTasks = ref<RuntimeTask[]>([])
  const pipelineJobs = ref<PipelineJob[]>([])
  const trainingJobs = ref<TrainingJob[]>([])
  const checkpointSummary = ref<CheckpointSummary[]>([])
  const runtimeMetrics = ref<any>(null)
  const trainingSummary = ref<any>(null)
  const deploymentSummary = ref<any>(null)
  const updatedAt = ref("")

  const traceEvents = ref<TraceEvent[]>([])
  const replayingTrace = ref(false)
  const traceError = ref("")

  async function loadDashboard() {
    if (loading.value) return

    loading.value = true
    error.value = ""
    try {
      const [
        runtimeTasksRes,
        pipelineJobsRes,
        trainingJobsRes,
        checkpointSummaryRes,
        runtimeMetricsRes,
        trainingSummaryRes,
        deploymentSummaryRes,
      ] = await Promise.all([
        adminApi.getRuntimeTasks(30, 0),
        adminApi.getPipelineJobs({ limit: 20, offset: 0 }),
        adminApi.getLLMTrainingJobs(20),
        adminApi.getRuntimeCheckpointSummary(20),
        adminApi.getRuntimeMetrics(120),
        adminApi.getLLMTrainingSummary(100),
        adminApi.getLLMDeploymentSummary(20),
      ])

      runtimeTasks.value = runtimeTasksRes.items || []
      pipelineJobs.value = pipelineJobsRes.jobs || []
      trainingJobs.value = trainingJobsRes.items || []
      checkpointSummary.value = checkpointSummaryRes.items || []
      runtimeMetrics.value = runtimeMetricsRes || null
      trainingSummary.value = trainingSummaryRes || null
      deploymentSummary.value = deploymentSummaryRes || null
      updatedAt.value = new Date().toISOString()
    } catch (caught: any) {
      error.value = caught?.response?.data?.detail || "加载任务中心失败。"
    } finally {
      loading.value = false
    }
  }

  async function replayTrace(traceId: string) {
    replayingTrace.value = true
    traceError.value = ""
    traceEvents.value = []
    try {
      const response = await adminApi.replayRuntimeTrace(traceId)
      traceEvents.value = response.events || []
      if (!traceEvents.value.length) {
        traceError.value = "没有找到这条运行轨迹，或该轨迹不属于当前租户。"
      }
    } catch (caught: any) {
      traceError.value = caught?.response?.data?.detail || "运行轨迹回放失败。"
    } finally {
      replayingTrace.value = false
    }
  }

  return {
    loading,
    error,
    runtimeTasks,
    pipelineJobs,
    trainingJobs,
    checkpointSummary,
    runtimeMetrics,
    trainingSummary,
    deploymentSummary,
    updatedAt,
    traceEvents,
    replayingTrace,
    traceError,
    loadDashboard,
    replayTrace,
  }
})
