import { defineStore } from "pinia"
import { ref } from "vue"
import { adminApi } from "@/api/admin"

type GenericRecord = Record<string, any>

export const useTasksStore = defineStore("tasks", () => {
  const loading = ref(false)
  const error = ref("")
  const runtimeTasks = ref<GenericRecord[]>([])
  const pipelineJobs = ref<GenericRecord[]>([])
  const trainingJobs = ref<GenericRecord[]>([])
  const checkpointSummary = ref<GenericRecord[]>([])
  const runtimeMetrics = ref<GenericRecord | null>(null)
  const trainingSummary = ref<GenericRecord | null>(null)
  const updatedAt = ref("")

  async function loadDashboard() {
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
      ] = await Promise.all([
        adminApi.getRuntimeTasks(30, 0),
        adminApi.getPipelineJobs({ limit: 20, offset: 0 }),
        adminApi.getLLMTrainingJobs(20),
        adminApi.getRuntimeCheckpointSummary(20),
        adminApi.getRuntimeMetrics(120),
        adminApi.getLLMTrainingSummary(100),
      ])

      runtimeTasks.value = runtimeTasksRes.items || []
      pipelineJobs.value = pipelineJobsRes.jobs || []
      trainingJobs.value = trainingJobsRes.items || []
      checkpointSummary.value = checkpointSummaryRes.items || []
      runtimeMetrics.value = runtimeMetricsRes || null
      trainingSummary.value = trainingSummaryRes || null
      updatedAt.value = new Date().toISOString()
    } catch (caught: any) {
      error.value = caught?.response?.data?.detail || "加载任务中心失败。"
    } finally {
      loading.value = false
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
    updatedAt,
    loadDashboard,
  }
})
