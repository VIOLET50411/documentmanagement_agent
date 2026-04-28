import { defineStore } from "pinia"
import { ref, type Ref } from "vue"

export interface DocumentListItem {
  id: string
  title?: string
  status?: string
  percentage?: number
  [key: string]: unknown
}

export interface UploadProgressItem {
  status: string
  percentage: number
  fileName?: string
}

export const useDocumentStore = defineStore("documents", () => {
  const documents: Ref<DocumentListItem[]> = ref([])
  const isLoading = ref(false)
  const totalCount = ref(0)
  const currentPage = ref(1)
  const uploadProgress: Ref<Record<string, UploadProgressItem>> = ref({})

  function setDocuments(docs: DocumentListItem[], total: number) {
    documents.value = docs
    totalCount.value = total
  }

  function updateUploadProgress(docId: string, status: string, percentage: number, fileName?: string) {
    uploadProgress.value[docId] = { status, percentage, fileName: fileName ?? uploadProgress.value[docId]?.fileName }
  }

  function clearUploadProgress(docId: string) {
    delete uploadProgress.value[docId]
  }

  return {
    documents,
    isLoading,
    totalCount,
    currentPage,
    uploadProgress,
    setDocuments,
    updateUploadProgress,
    clearUploadProgress,
  }
})
