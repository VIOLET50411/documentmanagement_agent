import http, { apiGet } from "./http"

export interface DocumentUploadMetadata {
  department?: string
  access_level?: string | number
}

export interface UploadSessionPayload extends DocumentUploadMetadata {
  file_name: string
  content_type: string
  file_size: number
  total_parts: number
}

export const documentsApi = {
  upload(file: File, metadata: DocumentUploadMetadata = {}) {
    const formData = new FormData()
    formData.append("file", file)
    if (metadata.department) formData.append("department", metadata.department)
    if (metadata.access_level !== undefined) formData.append("access_level", String(metadata.access_level))

    return http.post("/documents/upload", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  },

  createUploadSession(payload: UploadSessionPayload) {
    return http.post("/documents/upload/session", payload)
  },

  uploadChunk(uploadId: string, partNumber: number, totalParts: number, blob: Blob) {
    const formData = new FormData()
    formData.append("upload_id", uploadId)
    formData.append("part_number", String(partNumber))
    formData.append("total_parts", String(totalParts))
    formData.append("chunk", blob, `chunk-${partNumber}`)
    return http.post("/documents/upload/chunk", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
  },

  completeUpload(uploadId: string) {
    return http.post("/documents/upload/complete", null, {
      params: { upload_id: uploadId },
    })
  },

  list(params: Record<string, unknown> = {}) {
    return apiGet("/documents/", { params })
  },

  getStatus(docId: string) {
    return apiGet(`/documents/${docId}/status`)
  },

  getEvents(docId: string) {
    return apiGet(`/documents/${docId}/events`)
  },

  getOriginal(docId: string) {
    return http.get<Blob, Blob>(`/documents/${docId}/original`, {
      responseType: "blob",
    })
  },

  retry(docId: string) {
    return http.post(`/documents/${docId}/retry`)
  },

  delete(docId: string) {
    return http.delete(`/documents/${docId}`)
  },
}
