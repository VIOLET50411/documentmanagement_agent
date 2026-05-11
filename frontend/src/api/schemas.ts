import { z } from "zod"

export const userSchema = z.object({
  id: z.string().optional(),
  username: z.string(),
  email: z.string().optional(),
  role: z.string().optional().default("EMPLOYEE"),
  department: z.string().optional(),
  email_verified: z.boolean().optional().default(false),
  tenant_id: z.string().optional(),
  level: z.number().optional(),
})

export const loginResponseSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.string().optional().default("bearer"),
})

export const chatCitationSchema = z.object({
  doc_id: z.string().optional(),
  doc_title: z.string().optional(),
  page_number: z.number().nullable().optional(),
  section_title: z.string().nullable().optional(),
  snippet: z.string().optional(),
})

export const chatHistoryMessageSchema = z.object({
  id: z.string(),
  role: z.string(),
  content: z.string(),
  citations: z.array(chatCitationSchema).optional().default([]),
  created_at: z.string(),
})

export const chatHistorySchema = z.object({
  thread_id: z.string(),
  messages: z.array(chatHistoryMessageSchema).optional().default([]),
})

export const chatSessionSchema = z.object({
  id: z.string(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
})

export const chatSessionListSchema = z.object({
  items: z.array(chatSessionSchema).optional().default([]),
})

export type UserPayload = z.infer<typeof userSchema>
export type LoginResponse = z.infer<typeof loginResponseSchema>
export type ChatHistoryResponse = z.infer<typeof chatHistorySchema>
export type ChatHistoryMessage = z.infer<typeof chatHistoryMessageSchema>
export type ChatCitation = z.infer<typeof chatCitationSchema>
export type ChatSessionListResponse = z.infer<typeof chatSessionListSchema>
export type ChatSessionPayload = z.infer<typeof chatSessionSchema>
