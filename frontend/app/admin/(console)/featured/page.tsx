"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  HolderOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useI18n, type Translate } from "@/lib/i18n";
import {
  adminGetFeaturedCategories,
  adminCreateFeaturedCategory,
  adminUpdateFeaturedCategory,
  adminDeleteFeaturedCategory,
  adminReorderFeaturedCategories,
  adminGetFeaturedExamples,
  adminCreateFeaturedExample,
  adminGetFeaturedExample,
  adminUpdateFeaturedExample,
  adminDeleteFeaturedExample,
  adminReorderCategoryExamples,
  adminReviewFeaturedExample,
  adminUnlistFeaturedExample,
  type CategoryTone,
  type ExampleStatus,
  type ReviewState,
  type AdminFeaturedCategory as FeaturedCategory,
  type AdminFeaturedExample as FeaturedExample,
  type AdminFeaturedCounts as FeaturedCounts,
} from "@/lib/api/admin-client";
import {
  filterRows,
  REVIEW_DOT_COLOR,
  STATUS_TAG_COLOR,
  TONE_STYLE,
  reviewCycleLabel,
} from "./_helpers";
import { CATEGORY_TONES } from "./_constants";

const { Title, Text } = Typography;

const STATUS_LABEL_KEY: Record<ExampleStatus, string> = {
  pending: "adminFeatured.statusPending",
  live: "adminFeatured.statusLive",
  rejected: "adminFeatured.statusRejected",
  reviewing: "adminFeatured.statusReviewing",
  unlisted: "adminFeatured.statusUnlisted",
};

type CategoryForm = { name: string; tone: CategoryTone };
type ExampleForm = { question: string; reviewCycleDays: string };

function statusLabel(status: ExampleStatus, t: Translate) {
  return t(STATUS_LABEL_KEY[status] as Parameters<Translate>[0]);
}

function formatClickCount(n: number) {
  return n.toLocaleString();
}

function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  } catch {
    return iso;
  }
}

function reviewDisplayLabel(example: FeaturedExample): string {
  if (!example.expiresAt) return "无需复审";
  const date = formatDate(example.expiresAt);
  if (example.reviewState === "expired") return `已过期 · 请复核`;
  return `${date} 到期`;
}

export default function AdminFeaturedPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const [categoryForm] = Form.useForm<CategoryForm>();
  const [exampleForm] = Form.useForm<ExampleForm>();

  // ---- Server data ----
  const [categories, setCategories] = useState<FeaturedCategory[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  // Per-category: loaded items + counts
  const [examplesByCategory, setExamplesByCategory] = useState<
    Record<string, { items: FeaturedExample[]; counts: FeaturedCounts }>
  >({});
  const [currentCategoryLoading, setCurrentCategoryLoading] = useState(false);

  const [currentCategoryId, setCurrentCategoryId] = useState("");

  // ---- Filters ----
  const [categorySearch, setCategorySearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<ExampleStatus | "all">("all");
  const [reviewFilter, setReviewFilter] = useState<ReviewState | "all">("all");
  const [exampleSearch, setExampleSearch] = useState("");

  // ---- Category modal (add / rename) ----
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState("");
  const [categorySubmitting, setCategorySubmitting] = useState(false);

  // ---- Example modal (add / edit) ----
  const [exampleModalOpen, setExampleModalOpen] = useState(false);
  const [editingExampleId, setEditingExampleId] = useState("");
  const [exampleSubmitting, setExampleSubmitting] = useState(false);

  // ---- Audit modal ----
  const [auditExample, setAuditExample] = useState<FeaturedExample | null>(null);
  const [rejectVisible, setRejectVisible] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [auditSubmitting, setAuditSubmitting] = useState(false);

  // ---- Drag-to-reorder categories ----
  const draggingId = useRef("");
  const [dragOverId, setDragOverId] = useState("");

  // ---- Load categories ----
  const loadCategories = useCallback(async () => {
    setCategoriesLoading(true);
    try {
      const data = await adminGetFeaturedCategories();
      const cats = Array.isArray(data?.items) ? data.items : [];
      setCategories(cats);
      if (cats.length > 0) {
        setCurrentCategoryId((cur) => cur || cats[0].id);
      }
    } catch (err: unknown) {
      const e = err as { message?: string };
      message.error(e?.message ?? "加载分类失败");
    } finally {
      setCategoriesLoading(false);
    }
  }, [message]);

  // ---- Load examples for a category ----
  const loadCategoryExamples = useCallback(
    async (categoryId: string) => {
      if (!categoryId) return;
      setCurrentCategoryLoading(true);
      try {
        const data = await adminGetFeaturedExamples({ categoryId });
        const items = Array.isArray(data?.items) ? data.items : [];
        const counts = data?.counts ?? {
          total: 0, live: 0, pending: 0, reviewing: 0, rejected: 0, unlisted: 0, expiring: 0, expired: 0,
        };
        setExamplesByCategory((prev) => ({ ...prev, [categoryId]: { items, counts } }));
      } catch (err: unknown) {
        const e = err as { message?: string };
        message.error(e?.message ?? "加载示例失败");
      } finally {
        setCurrentCategoryLoading(false);
      }
    },
    [message]
  );

  useEffect(() => {
    loadCategories();
  }, [loadCategories]);

  useEffect(() => {
    if (currentCategoryId) {
      loadCategoryExamples(currentCategoryId);
    }
  }, [currentCategoryId, loadCategoryExamples]);

  const currentCategory = useMemo(
    () => categories.find((c) => c.id === currentCategoryId) ?? categories[0],
    [categories, currentCategoryId]
  );

  const currentCategoryData = useMemo(
    () => examplesByCategory[currentCategory?.id ?? ""] ?? { items: [], counts: { total: 0, live: 0, pending: 0, reviewing: 0, rejected: 0, unlisted: 0, expiring: 0, expired: 0 } },
    [examplesByCategory, currentCategory]
  );

  const counts = currentCategoryData.counts;

  const filteredRows = useMemo(
    () => filterRows(currentCategoryData.items, statusFilter, reviewFilter, exampleSearch),
    [currentCategoryData.items, statusFilter, reviewFilter, exampleSearch]
  );

  const visibleCategories = useMemo(() => {
    const kw = categorySearch.trim().toLowerCase();
    return categories.filter((c) => !kw || c.name.toLowerCase().includes(kw));
  }, [categories, categorySearch]);

  const summaryText = useMemo(() => {
    const parts = [t("adminFeatured.summary", { total: counts.total })];
    if (counts.pending) parts.push(t("adminFeatured.summaryPending", { count: counts.pending }));
    if (counts.reviewing) parts.push(t("adminFeatured.summaryReviewing", { count: counts.reviewing }));
    return parts.join("，");
  }, [counts, t]);

  // ---- Category actions ----
  function openAddCategory() {
    setEditingCategoryId("");
    categoryForm.setFieldsValue({ name: "", tone: CATEGORY_TONES[categories.length % CATEGORY_TONES.length] });
    setCategoryModalOpen(true);
  }

  function openRenameCategory() {
    if (!currentCategory) return;
    setEditingCategoryId(currentCategory.id);
    categoryForm.setFieldsValue({ name: currentCategory.name, tone: currentCategory.tone });
    setCategoryModalOpen(true);
  }

  async function submitCategory() {
    const values = await categoryForm.validateFields();
    const name = values.name.trim();
    const tone = values.tone;
    setCategorySubmitting(true);
    try {
      if (editingCategoryId) {
        await adminUpdateFeaturedCategory(editingCategoryId, { name, tone });
        message.success(t("adminFeatured.toastCategoryRenamed"));
      } else {
        const created = await adminCreateFeaturedCategory({ name, tone });
        setCurrentCategoryId(created.id);
        message.success(t("adminFeatured.toastCategoryAdded"));
      }
      setCategoryModalOpen(false);
      await loadCategories();
    } catch (err: unknown) {
      const e = err as { message?: string };
      message.error(e?.message ?? "操作失败");
    } finally {
      setCategorySubmitting(false);
    }
  }

  function deleteCurrentCategory() {
    if (!currentCategory) return;
    const target = currentCategory;
    modal.confirm({
      title: t("adminFeatured.deleteCategory"),
      content: t("adminFeatured.deleteCategoryConfirm", { name: target.name }),
      okText: t("adminFeatured.confirmDelete"),
      okButtonProps: { danger: true },
      cancelText: t("adminFeatured.confirmCancel"),
      onOk: async () => {
        try {
          await adminDeleteFeaturedCategory(target.id);
          message.success(t("adminFeatured.toastCategoryDeleted", { name: target.name }));
          await loadCategories();
          setCurrentCategoryId((cur) => {
            if (cur === target.id) {
              const remaining = categories.filter((c) => c.id !== target.id);
              return remaining[0]?.id ?? "";
            }
            return cur;
          });
        } catch (err: unknown) {
          const e = err as { message?: string; code?: string };
          if (e?.code === "FEATURED_CATEGORY_NOT_EMPTY") {
            message.error("请先移动或删除该分类下的所有示例");
          } else {
            message.error(e?.message ?? "删除失败");
          }
        }
      },
    });
  }

  async function reorderCategories(fromId: string, toId: string) {
    if (fromId === toId) return;
    const newOrder = [...categories];
    const from = newOrder.findIndex((c) => c.id === fromId);
    const to = newOrder.findIndex((c) => c.id === toId);
    if (from < 0 || to < 0) return;
    const [item] = newOrder.splice(from, 1);
    newOrder.splice(to, 0, item);
    // Optimistic update
    setCategories(newOrder);
    try {
      await adminReorderFeaturedCategories(newOrder.map((c) => c.id));
      message.success(t("adminFeatured.toastCategorySorted"));
    } catch (err: unknown) {
      const e = err as { message?: string };
      message.error(e?.message ?? "排序失败");
      await loadCategories();
    }
  }

  // ---- Example actions ----
  function openAddExample() {
    setEditingExampleId("");
    exampleForm.setFieldsValue({ question: "", reviewCycleDays: "null" });
    setExampleModalOpen(true);
  }

  async function openEditExample(example: FeaturedExample) {
    setEditingExampleId(example.id);
    exampleForm.setFieldsValue({
      question: example.question,
      reviewCycleDays: example.reviewCycleDays === null ? "null" : String(example.reviewCycleDays),
    });
    setExampleModalOpen(true);
  }

  async function submitExample() {
    const values = await exampleForm.validateFields();
    const question = values.question.trim();
    const reviewCycleDays = values.reviewCycleDays === "null" ? null : Number(values.reviewCycleDays);
    if (!currentCategory) return;

    setExampleSubmitting(true);
    try {
      if (editingExampleId) {
        await adminUpdateFeaturedExample(editingExampleId, { question, reviewCycleDays });
      } else {
        await adminCreateFeaturedExample({ categoryId: currentCategory.id, question, reviewCycleDays });
      }
      message.success(t("adminFeatured.toastExampleSaved"));
      setExampleModalOpen(false);
      await loadCategoryExamples(currentCategory.id);
    } catch (err: unknown) {
      const e = err as { message?: string };
      message.error(e?.message ?? "保存失败");
    } finally {
      setExampleSubmitting(false);
    }
  }

  async function moveExample(example: FeaturedExample, direction: -1 | 1) {
    if (!currentCategory) return;
    const items = currentCategoryData.items;
    const index = items.findIndex((r) => r.id === example.id);
    const toIndex = index + direction;
    if (index < 0 || toIndex < 0 || toIndex >= items.length) return;

    const newItems = [...items];
    const [item] = newItems.splice(index, 1);
    newItems.splice(toIndex, 0, item);

    // Optimistic update
    setExamplesByCategory((prev) => ({
      ...prev,
      [currentCategory.id]: { ...currentCategoryData, items: newItems },
    }));

    try {
      await adminReorderCategoryExamples(currentCategory.id, newItems.map((r) => r.id));
      message.success(t("adminFeatured.toastExampleSorted"));
    } catch (err: unknown) {
      const e = err as { message?: string; code?: string };
      if (e?.code === "FEATURED_ORDER_INVALID") {
        message.error("排序数据无效，请刷新后重试");
      } else {
        message.error(e?.message ?? "排序失败");
      }
      await loadCategoryExamples(currentCategory.id);
    }
  }

  function deleteExample(example: FeaturedExample) {
    modal.confirm({
      title: t("adminFeatured.deleteExample"),
      content: t("adminFeatured.deleteExampleConfirm", { name: example.question }),
      okText: t("adminFeatured.confirmDelete"),
      okButtonProps: { danger: true },
      cancelText: t("adminFeatured.confirmCancel"),
      onOk: async () => {
        try {
          await adminDeleteFeaturedExample(example.id);
          message.success(t("adminFeatured.toastExampleDeleted", { name: example.question }));
          if (currentCategory) await loadCategoryExamples(currentCategory.id);
        } catch (err: unknown) {
          const e = err as { message?: string; code?: string };
          if (e?.code === "FEATURED_EXAMPLE_NOT_FOUND") {
            message.warning("示例已不存在，正在刷新列表");
            if (currentCategory) await loadCategoryExamples(currentCategory.id);
          } else {
            message.error(e?.message ?? "删除失败");
          }
        }
      },
    });
  }

  function shelfExample(example: FeaturedExample) {
    modal.confirm({
      title: t("adminFeatured.shelfExample"),
      content: t("adminFeatured.shelfExampleConfirm", { name: example.question }),
      okText: t("adminFeatured.confirmShelf"),
      cancelText: t("adminFeatured.confirmCancel"),
      onOk: async () => {
        try {
          await adminUnlistFeaturedExample(example.id);
          message.success(t("adminFeatured.toastExampleShelved", { name: example.question }));
          if (currentCategory) await loadCategoryExamples(currentCategory.id);
        } catch (err: unknown) {
          const e = err as { message?: string; code?: string };
          if (e?.code === "FEATURED_INVALID_TRANSITION") {
            message.error("当前状态不允许下架操作");
            if (currentCategory) await loadCategoryExamples(currentCategory.id);
          } else {
            message.error(e?.message ?? "下架失败");
          }
        }
      },
    });
  }

  // ---- Audit actions ----
  async function openAudit(example: FeaturedExample) {
    try {
      // Fetch fresh detail to get updatedAt for expectedUpdatedAt
      const fresh = await adminGetFeaturedExample(example.id);
      setAuditExample(fresh);
      setRejectVisible(false);
      setRejectReason("");
    } catch (err: unknown) {
      const e = err as { message?: string; code?: string };
      if (e?.code === "FEATURED_EXAMPLE_NOT_FOUND") {
        message.warning("示例已不存在，正在刷新列表");
        if (currentCategory) await loadCategoryExamples(currentCategory.id);
      } else {
        message.error(e?.message ?? "加载示例详情失败");
      }
    }
  }

  function closeAudit() {
    setAuditExample(null);
    setRejectVisible(false);
    setRejectReason("");
  }

  async function auditPass() {
    if (!auditExample) return;
    setAuditSubmitting(true);
    try {
      await adminReviewFeaturedExample(auditExample.id, {
        decision: "approve",
        expectedUpdatedAt: auditExample.updatedAt,
      });
      message.success(t("adminFeatured.toastAuditPassed"));
      closeAudit();
      if (currentCategory) await loadCategoryExamples(currentCategory.id);
    } catch (err: unknown) {
      const e = err as { message?: string; code?: string };
      if (e?.code === "FEATURED_EXAMPLE_CHANGED") {
        message.error("示例内容已变更，请重新查看后审核");
        // Refresh the detail
        try {
          const fresh = await adminGetFeaturedExample(auditExample.id);
          setAuditExample(fresh);
        } catch {
          closeAudit();
          if (currentCategory) await loadCategoryExamples(currentCategory.id);
        }
      } else if (e?.code === "FEATURED_INVALID_TRANSITION") {
        message.error("当前状态不允许该审核操作");
        closeAudit();
        if (currentCategory) await loadCategoryExamples(currentCategory.id);
      } else {
        message.error(e?.message ?? "审核失败");
      }
    } finally {
      setAuditSubmitting(false);
    }
  }

  async function auditReject() {
    if (!rejectVisible) {
      setRejectVisible(true);
      return;
    }
    if (!rejectReason.trim()) {
      message.error(t("adminFeatured.auditRejectReasonRequired"));
      return;
    }
    if (!auditExample) return;
    setAuditSubmitting(true);
    try {
      await adminReviewFeaturedExample(auditExample.id, {
        decision: "reject",
        expectedUpdatedAt: auditExample.updatedAt,
        reason: rejectReason.trim(),
      });
      message.success(t("adminFeatured.toastAuditRejected"));
      closeAudit();
      if (currentCategory) await loadCategoryExamples(currentCategory.id);
    } catch (err: unknown) {
      const e = err as { message?: string; code?: string };
      if (e?.code === "FEATURED_EXAMPLE_CHANGED") {
        message.error("示例内容已变更，请重新查看后审核");
        try {
          const fresh = await adminGetFeaturedExample(auditExample.id);
          setAuditExample(fresh);
          setRejectVisible(false);
          setRejectReason("");
        } catch {
          closeAudit();
          if (currentCategory) await loadCategoryExamples(currentCategory.id);
        }
      } else {
        message.error(e?.message ?? "驳回失败");
      }
    } finally {
      setAuditSubmitting(false);
    }
  }

  const columns: TableColumnsType<FeaturedExample> = [
    {
      title: t("adminFeatured.colRank"),
      key: "rank",
      width: 96,
      render: (_, row, index) => (
        <div className="flex items-center gap-2">
          <div className="flex flex-col">
            <Button
              type="text"
              size="small"
              className="!h-4 !w-4 !min-w-0 !p-0 !leading-none"
              icon={<ArrowUpOutlined className="!text-[11px]" />}
              disabled={index === 0}
              aria-label={t("adminFeatured.moveUp")}
              onClick={() => moveExample(row, -1)}
            />
            <Button
              type="text"
              size="small"
              className="!h-4 !w-4 !min-w-0 !p-0 !leading-none"
              icon={<ArrowDownOutlined className="!text-[11px]" />}
              disabled={index === filteredRows.length - 1}
              aria-label={t("adminFeatured.moveDown")}
              onClick={() => moveExample(row, 1)}
            />
          </div>
          <span className="inline-grid h-6 min-w-6 place-items-center rounded-lg bg-[#f1f3f6] text-[13px] font-semibold text-[#111827]">
            {index + 1}
          </span>
        </div>
      ),
    },
    {
      title: t("adminFeatured.colQuestion"),
      key: "question",
      render: (_, row) => (
        <div className="min-w-0">
          <div className="break-words text-[#1f2933]">
            {row.question}
          </div>
          <div className="mt-1 text-xs text-[#8a8f98]">
            #{row.id}
            {row.rejectReason ? ` · 已驳回` : ""}
          </div>
        </div>
      ),
    },
    {
      title: t("adminFeatured.colStatus"),
      key: "status",
      width: 100,
      render: (_, row) => <Tag color={STATUS_TAG_COLOR[row.status]}>{statusLabel(row.status, t)}</Tag>,
    },
    {
      title: t("adminFeatured.colReview"),
      key: "review",
      width: 170,
      render: (_, row) => (
        <span className="inline-flex items-center gap-2 text-[13px] text-[#526174]">
          <span
            className="inline-block h-[7px] w-[7px] rounded-full"
            style={{ background: REVIEW_DOT_COLOR[row.reviewState] }}
          />
          {reviewDisplayLabel(row)}
        </span>
      ),
    },
    {
      title: t("adminFeatured.colUpdated"),
      key: "updated",
      width: 120,
      render: (_, row) => formatDate(row.updatedAt),
    },
    {
      title: t("adminFeatured.colAuthor"),
      key: "author",
      width: 100,
      render: (_, row) => row.authorName ?? "—",
    },
    {
      title: t("adminFeatured.colClicks"),
      key: "clicks",
      width: 100,
      onHeaderCell: () => ({ style: { whiteSpace: "nowrap" as const } }),
      render: (_, row) => formatClickCount(row.clickCount),
    },
    {
      title: t("adminFeatured.colActions"),
      key: "actions",
      width: 220,
      render: (_, row) => (
        <Space size="small">
          <Button size="small" onClick={() => openEditExample(row)}>
            {t("adminFeatured.editExample")}
          </Button>
          {row.status === "pending" || row.status === "reviewing" ? (
            <Button size="small" onClick={() => openAudit(row)}>
              {t("adminFeatured.viewAudit")}
            </Button>
          ) : row.status === "live" ? (
            <Button size="small" onClick={() => shelfExample(row)}>
              {t("adminFeatured.shelfExample")}
            </Button>
          ) : null}
          <Button size="small" danger onClick={() => deleteExample(row)}>
            {t("adminFeatured.deleteExample")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div className="mb-[18px]">
        <p className="text-xs uppercase tracking-[0.16em] text-[#8a8f98]">{t("adminFeatured.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">
          {t("adminFeatured.title")}
        </Title>
      </div>

      <div className="grid grid-cols-[266px_minmax(0,1fr)] gap-4 max-[900px]:grid-cols-1">
        {/* ---- Category rail ---- */}
        <Card className="min-w-0" styles={{ body: { padding: 16 } }}>
          <div className="mb-3 flex items-center justify-between">
            <Text strong className="text-[15px]">
              {t("adminFeatured.railTitle")}
            </Text>
            <Button
              type="primary"
              shape="circle"
              size="small"
              icon={<PlusOutlined />}
              aria-label={t("adminFeatured.addCategoryAria")}
              onClick={openAddCategory}
            />
          </div>
          <Input
            allowClear
            value={categorySearch}
            onChange={(e) => setCategorySearch(e.target.value)}
            placeholder={t("adminFeatured.searchCategoryPlaceholder")}
            className="mb-3"
          />
          <div className="mb-2 text-xs text-[#8a8f98]">{t("adminFeatured.railListLabel")}</div>
          <div className="grid gap-1.5">
            {categoriesLoading ? (
              <div className="flex justify-center py-6">
                <Spin size="small" />
              </div>
            ) : visibleCategories.length === 0 ? (
              <div className="py-6 text-center text-[13px] text-[#8a8f98]">{t("adminFeatured.categoryEmpty")}</div>
            ) : (
              visibleCategories.map((category) => {
                const catData = examplesByCategory[category.id];
                const catCounts = catData?.counts;
                const isActive = category.id === currentCategory?.id;
                const isDragOver = dragOverId === category.id;
                const tone = TONE_STYLE[category.tone];
                return (
                  <button
                    key={category.id}
                    type="button"
                    draggable
                    onClick={() => setCurrentCategoryId(category.id)}
                    onDragStart={() => {
                      draggingId.current = category.id;
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (draggingId.current && draggingId.current !== category.id) setDragOverId(category.id);
                    }}
                    onDragLeave={() => setDragOverId((cur) => (cur === category.id ? "" : cur))}
                    onDrop={(e) => {
                      e.preventDefault();
                      if (draggingId.current) reorderCategories(draggingId.current, category.id);
                      draggingId.current = "";
                      setDragOverId("");
                    }}
                    onDragEnd={() => {
                      draggingId.current = "";
                      setDragOverId("");
                    }}
                    className={[
                      "grid grid-cols-[14px_minmax(0,1fr)_auto] items-center gap-2 rounded-[9px] border px-2.5 py-2 text-left transition",
                      isActive ? "border-[#d8e7ff] bg-[#eaf3ff]" : "border-transparent hover:border-[#d8dee8] hover:bg-white",
                      isDragOver ? "!border-[#2f74e8] bg-[#f0f6ff]" : "",
                    ].join(" ")}
                  >
                    <HolderOutlined className="cursor-grab text-[#b1bbc9]" />
                    <span
                      className={["truncate text-[13px]", isActive ? "font-semibold text-[#1457d9]" : "text-[#1f2933]"].join(" ")}
                    >
                      {category.name}
                    </span>
                    {catCounts?.pending ? (
                      <Tag color="warning" className="!m-0 !px-1.5 !text-[11px]">
                        {t("adminFeatured.navPending", { count: catCounts.pending })}
                      </Tag>
                    ) : catCounts?.reviewing ? (
                      <Tag color="warning" className="!m-0 !px-1.5 !text-[11px]">
                        {t("adminFeatured.navReviewing", { count: catCounts.reviewing })}
                      </Tag>
                    ) : (
                      <span />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </Card>

        {/* ---- Main area ---- */}
        <div className="grid min-w-0 gap-4">
          {currentCategory ? (
            <>
              <Card className="min-w-0" styles={{ body: { padding: 20 } }}>
                <div className="flex flex-wrap items-start gap-4">
                  <span
                    className="grid h-11 w-11 shrink-0 place-items-center rounded-[10px] text-base font-semibold"
                    style={{ background: TONE_STYLE[currentCategory.tone].bg, color: TONE_STYLE[currentCategory.tone].color }}
                  >
                    {currentCategory.short}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <strong className="text-[16px] text-[#1f2933]">{currentCategory.name}</strong>
                      {counts.live > 0 ? <Tag color="success">{t("adminFeatured.showingBadge")}</Tag> : null}
                    </div>
                    <p className="mt-1 mb-2 text-[13px] text-[#8a8f98]">{summaryText}</p>
                    <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-[#526174]">
                      <span>
                        {t("adminFeatured.statTotal")} <strong className="text-[#1f2933]">{counts.total}</strong>
                      </span>
                      <span>
                        {t("adminFeatured.statLive")} <strong className="text-[#2f9e44]">{counts.live}</strong>
                      </span>
                      <span>
                        {t("adminFeatured.statPending")} <strong className="text-[#c27c0e]">{counts.pending}</strong>
                      </span>
                      <span>
                        {t("adminFeatured.statReviewing")} <strong className="text-[#c27c0e]">{counts.reviewing}</strong>
                      </span>
                    </div>
                  </div>
                  <Space wrap>
                    <Button onClick={openRenameCategory}>{t("adminFeatured.editCategory")}</Button>
                    <Button type="primary" icon={<PlusOutlined />} onClick={openAddExample}>
                      {t("adminFeatured.addExample")}
                    </Button>
                    <Button danger onClick={deleteCurrentCategory}>
                      {t("adminFeatured.deleteCategory")}
                    </Button>
                  </Space>
                </div>
              </Card>

              {(counts.expired > 0 || counts.expiring > 0) ? (
                <div className="flex items-center gap-3 rounded-lg border border-[#ffc9c9] bg-[#fff0f0] px-4 py-3 text-[13px] text-[#b4232d]">
                  <span className="h-2 w-2 shrink-0 rounded-full bg-[#ef4444]" />
                  <strong className="flex-1 font-semibold">
                    {t("adminFeatured.reviewAlert", { count: counts.expired + counts.expiring })}
                  </strong>
                  <Button
                    size="small"
                    danger
                    onClick={() => setReviewFilter("expired")}
                  >
                    {t("adminFeatured.reviewAlertView")}
                  </Button>
                </div>
              ) : null}

              <Card
                className="min-w-0"
                styles={{ body: { padding: 20 } }}
                title={
                  <span className="text-[16px] font-normal text-[#1f2933]">
                    {t("adminFeatured.listTitle")}{" "}
                    <span className="text-[13px] text-[#8a8f98]">
                      {t("adminFeatured.listCount", { count: filteredRows.length })}
                    </span>
                  </span>
                }
                extra={
                  <Space wrap>
                    <Select<ExampleStatus | "all">
                      value={statusFilter}
                      onChange={setStatusFilter}
                      style={{ width: 130 }}
                      options={[
                        { value: "all", label: t("adminFeatured.allStatus") },
                        { value: "pending", label: t("adminFeatured.statusPending") },
                        { value: "live", label: t("adminFeatured.statusLive") },
                        { value: "rejected", label: t("adminFeatured.statusRejected") },
                        { value: "reviewing", label: t("adminFeatured.statusReviewing") },
                        { value: "unlisted", label: t("adminFeatured.statusUnlisted") },
                      ]}
                    />
                    <Select<ReviewState | "all">
                      value={reviewFilter}
                      onChange={setReviewFilter}
                      style={{ width: 150 }}
                      options={[
                        { value: "all", label: t("adminFeatured.allReview") },
                        { value: "expired", label: t("adminFeatured.reviewExpired") },
                        { value: "expiring", label: t("adminFeatured.reviewExpiring") },
                        { value: "normal", label: t("adminFeatured.reviewNormal") },
                      ]}
                    />
                    <Input
                      allowClear
                      value={exampleSearch}
                      onChange={(e) => setExampleSearch(e.target.value)}
                      placeholder={t("adminFeatured.searchExamplePlaceholder")}
                      style={{ width: 220 }}
                    />
                  </Space>
                }
              >
                <Spin spinning={currentCategoryLoading}>
                  <Table<FeaturedExample>
                    rowKey="id"
                    columns={columns}
                    dataSource={filteredRows}
                    scroll={{ x: 1080 }}
                    locale={{ emptyText: t("adminFeatured.tableEmpty") }}
                    pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
                  />
                </Spin>
              </Card>
            </>
          ) : (
            <Card>
              <div className="py-16 text-center text-[13px] text-[#8a8f98]">{t("adminFeatured.categoryEmpty")}</div>
            </Card>
          )}
        </div>
      </div>

      {/* ---- Category modal ---- */}
      <Modal
        open={categoryModalOpen}
        title={editingCategoryId ? t("adminFeatured.categoryModalEditTitle") : t("adminFeatured.categoryModalAddTitle")}
        okText={t("adminFeatured.categorySave")}
        cancelText={t("adminFeatured.confirmCancel")}
        confirmLoading={categorySubmitting}
        onOk={submitCategory}
        onCancel={() => setCategoryModalOpen(false)}
      >
        <p className="mb-3 text-[13px] text-[#8a8f98]">{t("adminFeatured.categoryModalSubtitle")}</p>
        <Form form={categoryForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="name"
            label={t("adminFeatured.categoryNameLabel")}
            rules={[{ required: true, message: t("adminFeatured.categoryNameRequired") }]}
          >
            <Input placeholder={t("adminFeatured.categoryNamePlaceholder")} maxLength={60} />
          </Form.Item>
          <Form.Item
            name="tone"
            label={t("adminFeatured.categoryToneLabel")}
            rules={[{ required: true }]}
          >
            <Select
              options={CATEGORY_TONES.map((tone) => ({
                value: tone,
                label: (
                  <span className="inline-flex items-center gap-2">
                    <span
                      className="inline-block h-3 w-3 rounded-sm"
                      style={{ background: TONE_STYLE[tone].color }}
                    />
                    {t(`adminFeatured.tone_${tone}` as Parameters<Translate>[0])}
                  </span>
                ),
              }))}
            />
          </Form.Item>
        </Form>
        <p className="text-[12px] text-[#8a8f98]">{t("adminFeatured.categoryModalNote")}</p>
      </Modal>

      {/* ---- Example modal ---- */}
      <Modal
        open={exampleModalOpen}
        width={560}
        title={editingExampleId ? t("adminFeatured.exampleModalEditTitle") : t("adminFeatured.exampleModalAddTitle")}
        okText={t("adminFeatured.exampleSubmit")}
        cancelText={t("adminFeatured.confirmCancel")}
        confirmLoading={exampleSubmitting}
        onOk={submitExample}
        onCancel={() => setExampleModalOpen(false)}
      >
        <p className="mb-3 text-[13px] text-[#8a8f98]">
          {t("adminFeatured.exampleModalSubtitlePrefix")}
          {currentCategory?.name}
          {t("adminFeatured.exampleModalSubtitleSuffix")}
        </p>
        <Form form={exampleForm} layout="vertical" requiredMark={false}>
          <Form.Item
            name="question"
            label={t("adminFeatured.exampleQuestionLabel")}
            rules={[{ required: true, message: t("adminFeatured.exampleQuestionRequired") }]}
          >
            <Input.TextArea rows={4} placeholder={t("adminFeatured.exampleQuestionPlaceholder")} maxLength={4000} showCount />
          </Form.Item>
          <Form.Item
            name="reviewCycleDays"
            label={t("adminFeatured.exampleReviewCycleLabel")}
          >
            <Select
              options={[
                { value: "null", label: t("adminFeatured.exampleReviewCyclePermanent") },
                { value: "30", label: t("adminFeatured.exampleReviewCycle30") },
                { value: "60", label: t("adminFeatured.exampleReviewCycle60") },
                { value: "90", label: t("adminFeatured.exampleReviewCycle90") },
              ]}
            />
          </Form.Item>
        </Form>
        <p className="mt-3 mb-0 text-[12px] text-[#8a8f98]">
          {editingExampleId ? t("adminFeatured.exampleNoteEdit") : t("adminFeatured.exampleNoteAdd")}
        </p>
      </Modal>

      {/* ---- Audit modal ---- */}
      <Modal
        open={Boolean(auditExample)}
        width={560}
        title={t("adminFeatured.auditTitle")}
        footer={
          <Space>
            <Button danger loading={auditSubmitting} onClick={auditReject}>
              {t("adminFeatured.auditReject")}
            </Button>
            <Button type="primary" loading={auditSubmitting} onClick={auditPass}>
              {t("adminFeatured.auditPass")}
            </Button>
          </Space>
        }
        onCancel={closeAudit}
      >
        {auditExample ? (
          <div className="grid gap-3">
            <p className="text-[13px] text-[#8a8f98]">{t("adminFeatured.auditSubtitle")}</p>
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-[#526174]">
              <span>
                {t("adminFeatured.auditAuthor")}：<strong>{auditExample.authorName ?? "—"}</strong>
              </span>
              <span>
                {t("adminFeatured.auditCategory")}：<strong>{currentCategory?.name}</strong>
              </span>
              <span>
                {t("adminFeatured.auditCreated")}：<strong>{formatDate(auditExample.createdAt)}</strong>
              </span>
            </div>
            <div>
              <div className="mb-1 text-[12px] text-[#8a8f98]">{t("adminFeatured.auditQuestion")}</div>
              <p className="mb-0 text-[#1f2933]">{auditExample.question}</p>
            </div>
            <div>
              <div className="mb-1 text-[12px] text-[#8a8f98]">{t("adminFeatured.auditReviewMark")}</div>
              <p className="mb-0 text-[13px] text-[#526174]">
                {reviewCycleLabel(auditExample.reviewCycleDays)}
              </p>
            </div>
            {auditExample.rejectReason ? (
              <div>
                <div className="mb-1 text-[12px] text-[#8a8f98]">{t("adminFeatured.auditPreviousRejectReason")}</div>
                <p className="mb-0 whitespace-pre-wrap text-[13px] text-[#b4232d]">{auditExample.rejectReason}</p>
              </div>
            ) : null}
            {rejectVisible ? (
              <div>
                <div className="mb-1 text-[12px] text-[#8a8f98]">{t("adminFeatured.auditRejectReasonLabel")}</div>
                <Input.TextArea
                  rows={3}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder={t("adminFeatured.auditRejectReasonPlaceholder")}
                  maxLength={4000}
                />
              </div>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
