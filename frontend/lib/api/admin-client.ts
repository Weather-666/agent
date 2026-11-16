/**
 * Admin-side API client.
 *
 * Re-exports all shared types and wraps every API function so that requests
 * are made with `adminRequest` (which carries the admin token) instead of the
 * default user-side `request` instance.  Admin pages should import from here
 * instead of the individual API modules.
 */

import { adminRequest } from "../request";

// ─── Re-export all shared types ──────────────────────────────────────────────
// tenants.ts also defines BillingPeriod (conflicts with plans.ts), so we
// export tenants types explicitly, omitting the duplicate.

export type * from "./experts";
export type * from "./plans";
export type * from "./knowledge";
export type * from "./users";
export type * from "./skills";
export type {
  TenantType,
  TenantStatus,
  SubscriptionStatus,
  TenantSubscription,
  TenantPlan,
  TenantMonthlyCredits,
  TenantCreditSummary,
  TenantCreditLedgerEntry,
  TenantCreditLedgerResponse,
  TenantOrderSummary,
  TenantMember,
  Tenant,
  GetTenantsParams,
  TenantsResponse,
  TenantMembersResponse,
  CreateTenantParams,
  UpdateTenantParams,
  UpdateTenantStatusParams,
  UpdateTenantSubscriptionParams,
  AddTenantMemberParams,
  UpdateTenantMemberParams,
  GetTenantCreditsParams,
  GetTenantCreditLedgerParams,
  CreateCreditAdjustmentParams,
} from "./tenants";
export type * from "./audit";
export type * from "./featured";
export type * from "./mcp-connectors";
export type * from "./expert-categories";

// ─── Import API functions ─────────────────────────────────────────────────────

import * as expertsApi from "./experts";
import * as plansApi from "./plans";
import * as knowledgeApi from "./knowledge";
import * as usersApi from "./users";
import * as skillsApi from "./skills";
import * as tenantsApi from "./tenants";
import * as auditApi from "./audit";
import * as featuredApi from "./featured";
import * as mcpApi from "./mcp-connectors";
import * as categoriesApi from "./expert-categories";

// ─── experts ─────────────────────────────────────────────────────────────────

export const getExperts = () => expertsApi.getExperts(adminRequest);
export const getExpert = (expertId: string) => expertsApi.getExpert(expertId, adminRequest);
export const searchExpertsByName = (name: string) => expertsApi.searchExpertsByName(name, adminRequest);
export const searchExpertsByCategory = (categoryId: string) => expertsApi.searchExpertsByCategory(categoryId, adminRequest);
export const searchExpertsByStatus = (status: expertsApi.ExpertStatus) => expertsApi.searchExpertsByStatus(status, adminRequest);
export const createExpert = (data: expertsApi.CreateExpertParams) => expertsApi.createExpert(data, adminRequest);
export const updateExpert = (expertId: string, data: expertsApi.UpdateExpertParams) => expertsApi.updateExpert(expertId, data, adminRequest);
export const deleteExpert = (expertId: string) => expertsApi.deleteExpert(expertId, adminRequest);
export const updateExpertStatus = (expertId: string, status: "published" | "unlisted") => expertsApi.updateExpertStatus(expertId, status, adminRequest);

// ─── plans ───────────────────────────────────────────────────────────────────

export const getPlans = () => plansApi.getPlans(adminRequest);
export const createPlan = (data: plansApi.CreatePlanParams) => plansApi.createPlan(data, adminRequest);
export const updatePlan = (planId: string, data: plansApi.UpdatePlanParams) => plansApi.updatePlan(planId, data, adminRequest);
export const deletePlan = (planId: string) => plansApi.deletePlan(planId, adminRequest);
export const replacePlanPrices = (planId: string, data: plansApi.ReplacePlanPricesParams) => plansApi.replacePlanPrices(planId, data, adminRequest);
export const replacePlanEntitlements = (planId: string, data: plansApi.ReplacePlanEntitlementsParams) => plansApi.replacePlanEntitlements(planId, data, adminRequest);
export const replacePlanExperts = (planId: string, data: plansApi.ReplacePlanExpertsParams) => plansApi.replacePlanExperts(planId, data, adminRequest);

// ─── knowledge ───────────────────────────────────────────────────────────────

export const getKnowledgeBases = (status?: knowledgeApi.KnowledgeBaseStatusFilter) => knowledgeApi.getKnowledgeBases(status, adminRequest);
export const getKnowledgeBase = (knowledgeBaseId: string) => knowledgeApi.getKnowledgeBase(knowledgeBaseId, adminRequest);
export const createKnowledgeBase = (data: knowledgeApi.CreateKnowledgeBaseParams) => knowledgeApi.createKnowledgeBase(data, adminRequest);
export const updateKnowledgeBase = (knowledgeBaseId: string, data: knowledgeApi.UpdateKnowledgeBaseParams) => knowledgeApi.updateKnowledgeBase(knowledgeBaseId, data, adminRequest);
export const archiveKnowledgeBase = (knowledgeBaseId: string) => knowledgeApi.archiveKnowledgeBase(knowledgeBaseId, adminRequest);
export const activateKnowledgeBase = (knowledgeBaseId: string) => knowledgeApi.activateKnowledgeBase(knowledgeBaseId, adminRequest);
export const deleteKnowledgeBase = (knowledgeBaseId: string) => knowledgeApi.deleteKnowledgeBase(knowledgeBaseId, adminRequest);
export const getKnowledgeIndexReview = (knowledgeBaseId: string) => knowledgeApi.getKnowledgeIndexReview(knowledgeBaseId, adminRequest);
export const approveKnowledgeIndexReview = (knowledgeBaseId: string, batchToken: string) => knowledgeApi.approveKnowledgeIndexReview(knowledgeBaseId, batchToken, adminRequest);
export const getKnowledgeBaseDocuments = (knowledgeBaseId: string, params?: { limit?: number; offset?: number }) => knowledgeApi.getKnowledgeBaseDocuments(knowledgeBaseId, params, adminRequest);
export const requestDocumentUploadUrl = (knowledgeBaseId: string, data: knowledgeApi.DocumentUploadUrlParams) => knowledgeApi.requestDocumentUploadUrl(knowledgeBaseId, data, adminRequest);
export const requestDocumentUploadUrls = (knowledgeBaseId: string, data: knowledgeApi.DocumentUploadUrlsParams) => knowledgeApi.requestDocumentUploadUrls(knowledgeBaseId, data, adminRequest);
export const completeDocumentUpload = (knowledgeBaseId: string, data: knowledgeApi.CompleteDocumentUploadParams) => knowledgeApi.completeDocumentUpload(knowledgeBaseId, data, adminRequest);
export const completeDocumentUploads = (knowledgeBaseId: string, data: knowledgeApi.CompleteDocumentUploadsParams) => knowledgeApi.completeDocumentUploads(knowledgeBaseId, data, adminRequest);
export const uploadKnowledgeBaseDocument = (knowledgeBaseId: string, file: File) => knowledgeApi.uploadKnowledgeBaseDocument(knowledgeBaseId, file, adminRequest);
export const uploadKnowledgeBaseDocuments = (knowledgeBaseId: string, files: File[]) => knowledgeApi.uploadKnowledgeBaseDocuments(knowledgeBaseId, files, adminRequest);
export const deleteKnowledgeBaseDocument = (knowledgeBaseId: string, documentId: string) => knowledgeApi.deleteKnowledgeBaseDocument(knowledgeBaseId, documentId, adminRequest);
export const getKnowledgeBaseDocumentDownloadUrl = (knowledgeBaseId: string, documentId: string) => knowledgeApi.getKnowledgeBaseDocumentDownloadUrl(knowledgeBaseId, documentId, adminRequest);
export const { uploadDocumentToStorage, clearKnowledgeBasesCache } = knowledgeApi;

// ─── users ───────────────────────────────────────────────────────────────────

export const getPlatformUsers = () => usersApi.getPlatformUsers(adminRequest);
export const getPlatformRoles = () => usersApi.getPlatformRoles(adminRequest);
export const getUsers = (params?: usersApi.GetUsersParams) => usersApi.getUsers(params, adminRequest);
export const getUser = (userId: string) => usersApi.getUser(userId, adminRequest);
export const updateUser = (userId: string, data: usersApi.UpdateUserParams) => usersApi.updateUser(userId, data, adminRequest);
export const updateUserStatus = (userId: string, data: usersApi.UpdateUserStatusParams) => usersApi.updateUserStatus(userId, data, adminRequest);
export const getUserTenants = (userId: string) => usersApi.getUserTenants(userId, adminRequest);
export const createPlatformUser = (data: usersApi.CreatePlatformUserParams) => usersApi.createPlatformUser(data, adminRequest);
export const { activatePlatformUser } = usersApi;
export const grantPlatformRole = (userId: string, role: string) => usersApi.grantPlatformRole(userId, role, adminRequest);
export const revokePlatformRole = (userId: string, role: string) => usersApi.revokePlatformRole(userId, role, adminRequest);

// ─── skills ──────────────────────────────────────────────────────────────────

export const getSkills = (params?: skillsApi.GetSkillsParams) => skillsApi.getSkills(params, adminRequest);
export const uploadSkill = (file: File, slug?: string) => skillsApi.uploadSkill(file, slug, adminRequest);
export const getSkill = (slug: string) => skillsApi.getSkill(slug, adminRequest);
export const updateSkill = (slug: string, data: skillsApi.UpdateSkillParams) => skillsApi.updateSkill(slug, data, adminRequest);
export const deleteSkill = (slug: string, deleteFiles?: boolean) => skillsApi.deleteSkill(slug, deleteFiles, adminRequest);
export const getSkillFileText = (slug: string, path?: string) => skillsApi.getSkillFileText(slug, path, adminRequest);

// ─── tenants ─────────────────────────────────────────────────────────────────

export const getTenants = (params?: tenantsApi.GetTenantsParams) => tenantsApi.getTenants(params, adminRequest);
export const getTenant = (tenantId: string) => tenantsApi.getTenant(tenantId, adminRequest);
export const createTenant = (data: tenantsApi.CreateTenantParams) => tenantsApi.createTenant(data, adminRequest);
export const updateTenant = (tenantId: string, data: tenantsApi.UpdateTenantParams) => tenantsApi.updateTenant(tenantId, data, adminRequest);
export const updateTenantStatus = (tenantId: string, data: tenantsApi.UpdateTenantStatusParams) => tenantsApi.updateTenantStatus(tenantId, data, adminRequest);
export const updateTenantSubscription = (tenantId: string, data: tenantsApi.UpdateTenantSubscriptionParams) => tenantsApi.updateTenantSubscription(tenantId, data, adminRequest);
export const getTenantMembers = (tenantId: string) => tenantsApi.getTenantMembers(tenantId, adminRequest);
export const addTenantMember = (tenantId: string, data: tenantsApi.AddTenantMemberParams) => tenantsApi.addTenantMember(tenantId, data, adminRequest);
export const updateTenantMember = (tenantId: string, userId: string, data: tenantsApi.UpdateTenantMemberParams) => tenantsApi.updateTenantMember(tenantId, userId, data, adminRequest);
export const removeTenantMember = (tenantId: string, userId: string) => tenantsApi.removeTenantMember(tenantId, userId, adminRequest);
export const getTenantCredits = (tenantId: string, params?: tenantsApi.GetTenantCreditsParams) => tenantsApi.getTenantCredits(tenantId, params, adminRequest);
export const getTenantCreditLedger = (tenantId: string, params?: tenantsApi.GetTenantCreditLedgerParams) => tenantsApi.getTenantCreditLedger(tenantId, params, adminRequest);
export const createCreditAdjustment = (tenantId: string, data: tenantsApi.CreateCreditAdjustmentParams, idempotencyKey: string) => tenantsApi.createCreditAdjustment(tenantId, data, idempotencyKey, adminRequest);

// ─── audit ───────────────────────────────────────────────────────────────────

export const getAuditEvents = (params?: auditApi.GetAuditEventsParams) => auditApi.getAuditEvents(params, adminRequest);

// ─── featured ────────────────────────────────────────────────────────────────

export const adminGetFeaturedCategories = () => featuredApi.adminGetFeaturedCategories(adminRequest);
export const adminCreateFeaturedCategory = (data: { name: string; tone: featuredApi.CategoryTone }) => featuredApi.adminCreateFeaturedCategory(data, adminRequest);
export const adminUpdateFeaturedCategory = (id: string, data: { name?: string; tone?: featuredApi.CategoryTone }) => featuredApi.adminUpdateFeaturedCategory(id, data, adminRequest);
export const adminDeleteFeaturedCategory = (id: string) => featuredApi.adminDeleteFeaturedCategory(id, adminRequest);
export const adminReorderFeaturedCategories = (ids: string[]) => featuredApi.adminReorderFeaturedCategories(ids, adminRequest);
export const adminGetFeaturedExamples = (params?: featuredApi.AdminExamplesParams) => featuredApi.adminGetFeaturedExamples(params, adminRequest);
export const adminCreateFeaturedExample = (data: { categoryId: string; question: string; reviewCycleDays: number | null }) => featuredApi.adminCreateFeaturedExample(data, adminRequest);
export const adminGetFeaturedExample = (id: string) => featuredApi.adminGetFeaturedExample(id, adminRequest);
export const adminUpdateFeaturedExample = (id: string, data: { categoryId?: string; question?: string; reviewCycleDays?: number | null }) => featuredApi.adminUpdateFeaturedExample(id, data, adminRequest);
export const adminDeleteFeaturedExample = (id: string) => featuredApi.adminDeleteFeaturedExample(id, adminRequest);
export const adminReorderCategoryExamples = (categoryId: string, ids: string[]) => featuredApi.adminReorderCategoryExamples(categoryId, ids, adminRequest);
export const adminReviewFeaturedExample = (id: string, data: { decision: "approve" | "reject"; expectedUpdatedAt: string; reason?: string }) => featuredApi.adminReviewFeaturedExample(id, data, adminRequest);
export const adminUnlistFeaturedExample = (id: string) => featuredApi.adminUnlistFeaturedExample(id, adminRequest);

// ─── mcp-connectors ──────────────────────────────────────────────────────────

export const getMcpConnectors = () => mcpApi.getMcpConnectors(adminRequest);

// ─── expert-categories ───────────────────────────────────────────────────────

export const getExpertCategories = () => categoriesApi.getExpertCategories(adminRequest);
export const createExpertCategory = (data: categoriesApi.CreateExpertCategoryParams) => categoriesApi.createExpertCategory(data, adminRequest);
export const updateExpertCategory = (categoryId: string, data: categoriesApi.UpdateExpertCategoryParams) => categoriesApi.updateExpertCategory(categoryId, data, adminRequest);
export const deleteExpertCategory = (categoryId: string) => categoriesApi.deleteExpertCategory(categoryId, adminRequest);
