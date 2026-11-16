"use client";

import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import Link from "next/link";
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tabs,
  Typography,
  type TableColumnsType,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { useI18n, type Translate } from "@/lib/i18n";
import { getExperts, type Expert } from "@/lib/api/admin-client";
import {
  createPlan,
  deletePlan,
  getPlans,
  replacePlanEntitlements,
  replacePlanExperts,
  replacePlanPrices,
  updatePlan,
  type Plan,
  type PlanStatus,
} from "@/lib/api/admin-client";
import { FieldLabel } from "./_field-label";
import {
  buildPrices,
  defaultForm,
  formatDate,
  formatInteger,
  formatPrice,
  getErrorMessage,
  getPlanType,
  getSubscriberCount,
  getTenantSubscriptionTypeFilter,
  isIntegerInRange,
  parsePositiveInt,
  planToForm,
  PLAN_LEVEL_MAX,
  PLAN_LEVEL_MIN,
  PLAN_SORT_ORDER_MAX,
  PLAN_SORT_ORDER_MIN,
  type PlanForm,
} from "./_helpers";

const { Title, Text } = Typography;

const CORE_PLAN_CODES = new Set(["plan_free", "plan_pro", "plan_max", "plan_business"]);

function LocalizedContentFields({
  form,
  setForm,
  language,
  t,
}: {
  form: PlanForm;
  setForm: Dispatch<SetStateAction<PlanForm>>;
  language: "zh" | "en";
  t: Translate;
}) {
  const prefix = language === "zh" ? "zh" : "en";
  const field = (name: "Subtitle" | "Description" | "BadgeLabel" | "HighlightItems") => `${prefix}${name}` as keyof PlanForm;
  const update = (name: "Subtitle" | "Description" | "BadgeLabel" | "HighlightItems", value: string) => {
    setForm((previous) => ({ ...previous, [field(name)]: value }));
  };
  return (
    <Row gutter={[12, 12]}>
      <Col span={24}>
        <FieldLabel text={t("adminPlans.fieldDescription")} />
        <Input.TextArea rows={3} value={form[field("Description")] as string} onChange={(event) => update("Description", event.target.value)} placeholder={t("adminPlans.descriptionPlaceholder")} />
      </Col>
      <Col span={8}>
        <FieldLabel text={t("adminPlans.fieldSubtitle")} />
        <Input value={form[field("Subtitle")] as string} onChange={(event) => update("Subtitle", event.target.value)} placeholder={t("adminPlans.subtitlePlaceholder")} />
      </Col>
      <Col span={8}>
        <FieldLabel text={t("adminPlans.fieldBadgeLabel")} />
        <Input value={form[field("BadgeLabel")] as string} onChange={(event) => update("BadgeLabel", event.target.value)} placeholder={t("adminPlans.badgeLabelPlaceholder")} />
      </Col>
      <Col span={8}>
        <FieldLabel text={t("adminPlans.fieldHighlightItems")} tooltip={t("adminPlans.highlightItemsTooltip")} />
        <Input value={form[field("HighlightItems")] as string} onChange={(event) => update("HighlightItems", event.target.value)} placeholder={t("adminPlans.highlightItemsPlaceholder")} />
      </Col>
    </Row>
  );
}

export default function AdminPlansPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [experts, setExperts] = useState<Expert[]>([]);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<PlanStatus | "">("");
  const [isLoading, setIsLoading] = useState(true);
  const [referencesLoading, setReferencesLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPlanId, setEditingPlanId] = useState("");
  const [form, setForm] = useState<PlanForm>(defaultForm);
  const [submitting, setSubmitting] = useState(false);
  const [pendingPlanId, setPendingPlanId] = useState("");
  const [contentLanguage, setContentLanguage] = useState<"zh" | "en">("zh");

  const statusOptions: Array<{ value: PlanStatus | ""; label: string }> = [
    { value: "", label: t("adminPlans.statusAll") },
    { value: "active", label: t("adminPlans.statusActive") },
    { value: "disabled", label: t("adminPlans.statusDisabled") },
  ];

  useEffect(() => {
    let ignore = false;

    Promise.all([
      getPlans().catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminPlans.loadPlansFailed")));
        return { items: [] };
      }),
      getExperts().catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminPlans.loadExpertsFailed")));
        return { items: [] };
      }),
    ])
      .then(([plansResponse, expertsResponse]) => {
        if (ignore) return;
        setPlans(Array.isArray(plansResponse.items) ? plansResponse.items : []);
        setExperts(Array.isArray(expertsResponse.items) ? expertsResponse.items : []);
      })
      .finally(() => {
        if (!ignore) {
          setIsLoading(false);
          setReferencesLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [t, message]);

  const expertNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    experts.forEach((expert) => {
      map[expert.id] = expert.name;
    });
    return map;
  }, [experts]);

  const filteredPlans = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();

    return plans
      .filter((plan) => {
        const matchesKeyword =
          !normalizedKeyword ||
          [plan.name, plan.code, plan.description, ...plan.expertIds.map((id) => expertNameMap[id] || id)]
            .join(" ")
            .toLowerCase()
            .includes(normalizedKeyword);
        const matchesStatus = !statusFilter || plan.status === statusFilter;
        return matchesKeyword && matchesStatus;
      })
      .sort((a, b) => a.sortOrder - b.sortOrder || a.level - b.level);
  }, [keyword, plans, statusFilter, expertNameMap]);

  const stats = useMemo(() => {
    const active = plans.filter((plan) => plan.status === "active").length;
    const paid = plans.filter((plan) => plan.prices.some((price) => price.amountCents > 0 || price.billingPeriod === "sales")).length;
    const subscriberTotal = plans.reduce((sum, plan) => sum + (getSubscriberCount(plan) ?? 0), 0);

    return [
      { label: t("adminPlans.statTotal"), value: plans.length.toLocaleString("zh-CN"), tone: "text-[#111827]" },
      { label: t("adminPlans.statusActive"), value: active.toLocaleString("zh-CN"), tone: "text-[#2f9e44]" },
      { label: t("adminPlans.statPaid"), value: paid.toLocaleString("zh-CN"), tone: "text-[#1d4ed8]" },
      { label: t("adminPlans.statSubscribers"), value: subscriberTotal ? subscriberTotal.toLocaleString("zh-CN") : "-", tone: "text-[#c27c0e]" },
    ];
  }, [plans, t]);

  function closeModal() {
    setIsModalOpen(false);
    setEditingPlanId("");
    setForm(defaultForm);
    setContentLanguage("zh");
  }

  function openCreateModal() {
    setEditingPlanId("");
    const defaultExpert = experts.find((expert) => expert.id === "expert_default") ?? experts[0];
    setForm({
      ...defaultForm,
      type: t("adminPlans.typePersonalPaid"),
      sortOrder: String((plans.length + 1) * 10),
      level: String(plans.length + 1),
      expertIds: defaultExpert?.id ? [defaultExpert.id] : [],
    });
    setIsModalOpen(true);
  }

  function openEditModal(plan: Plan) {
    setEditingPlanId(plan.id);
    setForm(planToForm(plan));
    setIsModalOpen(true);
  }

  function toggleExpert(expertId: string) {
    setForm((prev) => {
      const exists = prev.expertIds.includes(expertId);
      return {
        ...prev,
        expertIds: exists ? prev.expertIds.filter((id) => id !== expertId) : [...prev.expertIds, expertId],
      };
    });
  }

  async function handleSubmit() {
    const name = form.name.trim();
    const zhDescription = form.zhDescription.trim();
    const enDescription = form.enDescription.trim();
    const level = parsePositiveInt(form.level, 0);

    if (!name || !form.type || (!zhDescription && !enDescription) || level <= 0) {
      message.error(t("adminPlans.formRequired"));
      return;
    }

    if (!isIntegerInRange(form.level, PLAN_LEVEL_MIN, PLAN_LEVEL_MAX)) {
      message.error(t("adminPlans.levelRange", { min: PLAN_LEVEL_MIN, max: PLAN_LEVEL_MAX }));
      return;
    }

    if (!isIntegerInRange(form.sortOrder, PLAN_SORT_ORDER_MIN, PLAN_SORT_ORDER_MAX)) {
      message.error(t("adminPlans.sortRange", { min: PLAN_SORT_ORDER_MIN, max: PLAN_SORT_ORDER_MAX }));
      return;
    }

    const creditLimit = form.monthlyCreditLimit.trim();
    const seatLimit = form.seatLimit.trim();

    if (!/^\d+$/.test(creditLimit) || !/^\d+$/.test(seatLimit)) {
      message.error(t("adminPlans.entitlementRequired"));
      return;
    }

    if (Number.parseInt(seatLimit, 10) < 1) {
      message.error(t("adminPlans.seatMin"));
      return;
    }

    setSubmitting(true);

    const localizedContent = {
      zh: {
        subtitle: form.zhSubtitle.trim() || null,
        description: zhDescription || null,
        badgeLabel: form.zhBadgeLabel.trim() || null,
        highlightItems: form.zhHighlightItems.split(";").map((s) => s.trim()).filter(Boolean),
      },
      en: {
        subtitle: form.enSubtitle.trim() || null,
        description: enDescription || null,
        badgeLabel: form.enBadgeLabel.trim() || null,
        highlightItems: form.enHighlightItems.split(";").map((s) => s.trim()).filter(Boolean),
      },
    };
    if (form.status === "active" && Object.values(localizedContent).some((item) => !item.subtitle || !item.description || !item.highlightItems.length)) {
      message.error(t("adminPlans.publishLocalizationRequired"));
      setSubmitting(false);
      return;
    }

    const basePayload = {
      name,
      level,
      description: zhDescription || enDescription,
      typeLabel: form.type,
      subtitle: form.zhSubtitle.trim() || undefined,
      badgeLabel: form.zhBadgeLabel.trim() || undefined,
      highlightItems: localizedContent.zh.highlightItems,
      localizedContent,
      status: form.status,
      isRecommended: form.isRecommended,
      sortOrder: parsePositiveInt(form.sortOrder, level * 10),
    };

    try {
      let saved = editingPlanId
        ? await updatePlan(editingPlanId, basePayload)
        : await createPlan(basePayload);

      saved = await replacePlanPrices(saved.id, buildPrices(form, t));
      saved = await replacePlanEntitlements(saved.id, {
        monthlyCreditLimit: parsePositiveInt(form.monthlyCreditLimit, 0),
        allExperts: form.allExperts,
        seatLimit: Math.max(parsePositiveInt(form.seatLimit, 1), 1),
        singleTurnTokenLimit: form.singleTurnTokenLimit.trim()
          ? parsePositiveInt(form.singleTurnTokenLimit, 0)
          : null,
        modelTiers: form.modelTiers
          .split(/[,\n]/)
          .map((tier) => tier.trim())
          .filter(Boolean),
        features: {
          teamManagement: form.featureTeamManagement,
          apiAccess: form.featureApiAccess,
          privateDeployment: form.featurePrivateDeployment,
        },
      });
      saved = await replacePlanExperts(saved.id, { expertIds: form.expertIds });

      setPlans((prev) => {
        if (!editingPlanId) return [saved, ...prev];
        return prev.map((plan) => (plan.id === saved.id ? saved : plan));
      });
      message.success(editingPlanId ? t("adminPlans.updatedMessage") : t("adminPlans.createdMessage"));
      closeModal();
    } catch (err) {
      message.error(getErrorMessage(err, editingPlanId ? t("adminPlans.updateFailed") : t("adminPlans.createFailed")));
    } finally {
      setSubmitting(false);
    }
  }

  async function togglePlanStatus(plan: Plan) {
    const nextStatus: PlanStatus = plan.status === "active" ? "disabled" : "active";
    setPendingPlanId(plan.id);

    try {
      const updated = await updatePlan(plan.id, { status: nextStatus });
      setPlans((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      message.success(nextStatus === "active" ? t("adminPlans.planPublished") : t("adminPlans.planUnpublished"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminPlans.updateStatusFailed")));
    } finally {
      setPendingPlanId("");
    }
  }

  async function handleDeletePlan(plan: Plan) {
    setPendingPlanId(plan.id);

    try {
      await deletePlan(plan.id);
      setPlans((prev) => prev.filter((item) => item.id !== plan.id));
      message.success(t("adminPlans.planDeleted"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminPlans.deleteFailed")));
    } finally {
      setPendingPlanId("");
    }
  }

  function confirmToggleStatus(plan: Plan) {
    const isActive = plan.status === "active";
    modal.confirm({
      title: isActive ? t("adminPlans.confirmUnpublishTitle") : t("adminPlans.confirmPublishTitle"),
      content: isActive
        ? t("adminPlans.confirmUnpublishMessage", { name: plan.name })
        : t("adminPlans.confirmPublishMessage", { name: plan.name }),
      okText: isActive ? t("adminPlans.confirmUnpublishConfirm") : t("adminPlans.confirmPublishConfirm"),
      cancelText: t("adminPlans.confirmCancel"),
      onOk: () => togglePlanStatus(plan),
    });
  }

  function confirmDelete(plan: Plan) {
    modal.confirm({
      title: t("adminPlans.confirmDeleteTitle"),
      content: t("adminPlans.confirmDeleteMessage", { name: plan.name }),
      okText: t("adminPlans.confirmDeleteConfirm"),
      okButtonProps: { danger: true },
      cancelText: t("adminPlans.confirmCancel"),
      onOk: () => handleDeletePlan(plan),
    });
  }

  const columns: TableColumnsType<Plan> = [
    {
      title: t("adminPlans.colPlan"),
      key: "plan",
      fixed: "left",
      width: 200,
      render: (_, plan) => (
        <div title={plan.description || plan.name}>
          <strong className="block truncate text-[#111827]">{plan.name}</strong>
          {plan.isRecommended ? <Tag color="blue" className="!mt-1">{t("adminPlans.recommended")}</Tag> : null}
        </div>
      ),
    },
    { title: t("adminPlans.colType"), key: "type", render: (_, plan) => <Tag>{getPlanType(plan, t)}</Tag> },
    { title: t("adminPlans.colLevel"), dataIndex: "level", key: "level" },
    { title: t("adminPlans.colMonthlyPrice"), key: "monthly", render: (_, plan) => formatPrice(plan, "monthly", t) },
    { title: t("adminPlans.colYearlyPrice"), key: "yearly", render: (_, plan) => formatPrice(plan, "yearly", t) },
    { title: t("adminPlans.colCreditLimit"), key: "credits", render: (_, plan) => formatInteger(plan.entitlements?.monthlyCreditLimit) },
    {
      title: t("adminPlans.colExpertScope"),
      key: "experts",
      width: 200,
      render: (_, plan) =>
        plan.entitlements?.allExperts ? (
          <Tag color="blue">{t("adminPlans.allExpertsLabel")}</Tag>
        ) : plan.expertIds.length ? (
          <Space size={[4, 4]} wrap>
            {plan.expertIds.map((id) => (
              <Tag key={id} color="geekblue" className="!m-0">{expertNameMap[id] || id}</Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary" className="text-xs">{t("adminPlans.expertNotConfigured")}</Text>
        ),
    },
    { title: t("adminPlans.colSeats"), key: "seats", render: (_, plan) => plan.entitlements?.seatLimit ?? "-" },
    { title: t("adminPlans.colUpdatedAt"), key: "updatedAt", render: (_, plan) => formatDate(plan.updatedAt) },
    {
      title: t("adminPlans.colStatus"),
      key: "status",
      render: (_, plan) => (
        <Tag color={plan.status === "active" ? "green" : "gold"}>
          {plan.status === "active" ? t("adminPlans.statusActive") : t("adminPlans.statusDisabled")}
        </Tag>
      ),
    },
    {
      title: t("adminPlans.colSubscribers"),
      key: "subscribers",
      render: (_, plan) =>
        typeof getSubscriberCount(plan) === "number" ? (
          <Link
            href={`/admin/users-permissions/tenants?subscriptionType=${encodeURIComponent(getTenantSubscriptionTypeFilter(plan, t))}`}
            className="font-medium text-[#1d4ed8] hover:underline"
          >
            {formatInteger(getSubscriberCount(plan))}
          </Link>
        ) : (
          "-"
        ),
    },
    {
      title: t("adminPlans.colActions"),
      key: "actions",
      fixed: "right",
      width: 200,
      render: (_, plan) => (
        <Space wrap>
          <Button size="small" onClick={() => openEditModal(plan)}>{t("adminPlans.actionEdit")}</Button>
          <Button size="small" loading={pendingPlanId === plan.id} onClick={() => confirmToggleStatus(plan)}>
            {plan.status === "active" ? t("adminPlans.actionUnpublish") : t("adminPlans.actionPublish")}
          </Button>
          {plan.status !== "active" && !CORE_PLAN_CODES.has(plan.code) ? (
            <Button size="small" danger disabled={pendingPlanId === plan.id} onClick={() => confirmDelete(plan)}>
              {t("adminPlans.actionDelete")}
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div className="grid min-w-0 gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminPlans.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminPlans.pageTitle")}</Title>
      </div>

      <Row gutter={[12, 12]}>
        {stats.map((item) => (
          <Col key={item.label} xs={12} md={6}>
            <Card size="small">
              <Text type="secondary" className="text-sm">{item.label}</Text>
              <strong className={`mt-2 block text-2xl font-semibold ${item.tone}`}>{item.value}</strong>
            </Card>
          </Col>
        ))}
      </Row>

      <Card className="min-w-0">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{t("adminPlans.listTitle")}</Title>
            <Text type="secondary" className="text-sm">{t("adminPlans.listSubtitle")}</Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
            {t("adminPlans.createPlan")}
          </Button>
        </div>

        <Space size="middle" wrap className="mb-4 w-full">
          <Input.Search
            allowClear
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder={t("adminPlans.searchPlaceholder")}
            style={{ width: 320 }}
          />
          <Select
            value={statusFilter}
            onChange={(value) => setStatusFilter(value)}
            style={{ width: 220 }}
            options={statusOptions}
          />
        </Space>

        <Table<Plan>
          rowKey="id"
          columns={columns}
          dataSource={filteredPlans}
          loading={isLoading}
          scroll={{ x: 1600 }}
          locale={{ emptyText: t("adminPlans.emptyList") }}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
        />
      </Card>

      <Modal
        open={isModalOpen}
        title={editingPlanId ? t("adminPlans.modalEditTitle") : t("adminPlans.createPlan")}
        width={920}
        onCancel={closeModal}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={editingPlanId ? t("adminPlans.save") : t("adminPlans.saveDraft")}
        cancelText={t("adminPlans.cancel")}
        mask={{ closable: false }}
      >
        <div className="mt-2 grid gap-6">
          <section>
            <p className="mb-3 text-sm font-semibold text-[#111827]">{t("adminPlans.section1Title")}</p>
            <Row gutter={[12, 12]} align="bottom">
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldName")} />
                <Input
                  value={form.name}
                  onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                  placeholder={t("adminPlans.fieldNamePlaceholder")}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldType")} />
                <Select
                  className="w-full"
                  value={form.type || undefined}
                  onChange={(value) => setForm((prev) => ({ ...prev, type: value }))}
                  options={[
                    { value: t("adminPlans.typeFree"), label: t("adminPlans.typeFree") },
                    { value: t("adminPlans.typePersonalPaid"), label: t("adminPlans.typePersonalPaid") },
                    { value: t("adminPlans.typeTeamBusiness"), label: t("adminPlans.typeTeamBusiness") },
                    { value: t("adminPlans.typeEnterprise"), label: t("adminPlans.typeEnterprise") },
                  ]}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldStatus")} />
                <Select
                  className="w-full"
                  value={form.status}
                  onChange={(value) => setForm((prev) => ({ ...prev, status: value as PlanStatus }))}
                  options={[
                    { value: "disabled", label: t("adminPlans.statusDisabled") },
                    { value: "active", label: t("adminPlans.statusActive") },
                  ]}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldLevel")} tooltip={t("adminPlans.levelTooltip")} />
                <InputNumber
                  style={{ width: "100%" }}
                  min={PLAN_LEVEL_MIN}
                  max={PLAN_LEVEL_MAX}
                  step={1}
                  value={form.level === "" ? null : Number(form.level)}
                  onChange={(value) => setForm((prev) => ({ ...prev, level: value == null ? "" : String(value) }))}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldSort")} tooltip={t("adminPlans.sortTooltip")} />
                <InputNumber
                  style={{ width: "100%" }}
                  min={PLAN_SORT_ORDER_MIN}
                  max={PLAN_SORT_ORDER_MAX}
                  step={1}
                  value={form.sortOrder === "" ? null : Number(form.sortOrder)}
                  onChange={(value) => setForm((prev) => ({ ...prev, sortOrder: value == null ? "" : String(value) }))}
                />
              </Col>
              <Col span={8} className="pb-1.5">
                <Checkbox
                  checked={form.isRecommended}
                  onChange={(event) => setForm((prev) => ({ ...prev, isRecommended: event.target.checked }))}
                >
                  {t("adminPlans.recommended")}
                </Checkbox>
              </Col>
              <Col span={24}>
                <Tabs activeKey={contentLanguage} onChange={(key) => setContentLanguage(key as "zh" | "en")} items={[
                  { key: "zh", label: t("adminPlans.contentChinese"), children: <LocalizedContentFields form={form} setForm={setForm} language="zh" t={t} /> },
                  { key: "en", label: t("adminPlans.contentEnglish"), children: <LocalizedContentFields form={form} setForm={setForm} language="en" t={t} /> },
                ]} />
              </Col>
            </Row>
          </section>

          <section>
            <p className="mb-3 text-sm font-semibold text-[#111827]">{t("adminPlans.section2Title")}</p>
            <Row gutter={[12, 12]} align="bottom">
              <Col span={8}>
                <FieldLabel text={t("adminPlans.fieldCurrency")} />
                <Select
                  className="w-full"
                  value={form.currency}
                  onChange={(value) => {
                    if (value !== form.currency) message.warning(t("adminPlans.currencyNoConversion"));
                    setForm((prev) => ({ ...prev, currency: value }));
                  }}
                  options={[{ value: "CNY", label: t("adminPlans.currencyCny") }, { value: "USD", label: t("adminPlans.currencyUsd") }]}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={`${t("adminPlans.fieldMonthlyPrice")} (${form.currency})`} />
                <Input
                  value={form.monthlyPrice}
                  onChange={(event) => setForm((prev) => ({ ...prev, monthlyPrice: event.target.value }))}
                  placeholder={t("adminPlans.monthlyPricePlaceholder")}
                />
              </Col>
              <Col span={8}>
                <FieldLabel text={`${t("adminPlans.fieldYearlyPrice")} (${form.currency})`} />
                <Input
                  value={form.yearlyPrice}
                  onChange={(event) => setForm((prev) => ({ ...prev, yearlyPrice: event.target.value }))}
                  placeholder={t("adminPlans.yearlyPricePlaceholder")}
                />
              </Col>
              <Col span={8} className="pb-1.5">
                <Checkbox
                  checked={form.salesPrice}
                  onChange={(event) => setForm((prev) => ({ ...prev, salesPrice: event.target.checked }))}
                >
                  {t("adminPlans.salesPriceLabel")}
                </Checkbox>
              </Col>
            </Row>
          </section>

          <section>
            <p className="mb-3 text-sm font-semibold text-[#111827]">{t("adminPlans.section3Title")}</p>
            <Row gutter={[12, 12]}>
              <Col span={6}>
                <FieldLabel text={t("adminPlans.fieldCreditLimit")} required />
                <InputNumber
                  style={{ width: "100%" }}
                  min={0}
                  value={form.monthlyCreditLimit === "" ? null : Number(form.monthlyCreditLimit)}
                  onChange={(value) => setForm((prev) => ({ ...prev, monthlyCreditLimit: value == null ? "" : String(value) }))}
                />
              </Col>
              <Col span={6}>
                <FieldLabel text={t("adminPlans.fieldSeats")} required />
                <InputNumber
                  style={{ width: "100%" }}
                  min={1}
                  value={form.seatLimit === "" ? null : Number(form.seatLimit)}
                  onChange={(value) => setForm((prev) => ({ ...prev, seatLimit: value == null ? "" : String(value) }))}
                />
              </Col>
              <Col span={6}>
                <FieldLabel text={t("adminPlans.fieldSingleTurnToken")} />
                <InputNumber
                  style={{ width: "100%" }}
                  min={0}
                  value={form.singleTurnTokenLimit === "" ? null : Number(form.singleTurnTokenLimit)}
                  onChange={(value) => setForm((prev) => ({ ...prev, singleTurnTokenLimit: value == null ? "" : String(value) }))}
                  placeholder={t("adminPlans.singleTurnPlaceholder")}
                />
              </Col>
              <Col span={12}>
                <FieldLabel text={t("adminPlans.fieldModelTiers")} />
                <Input
                  value={form.modelTiers}
                  onChange={(event) => setForm((prev) => ({ ...prev, modelTiers: event.target.value }))}
                  placeholder="core, enhanced"
                />
              </Col>
              <Col span={12}>
                <FieldLabel text={t("adminPlans.fieldFeatureToggles")} />
                <div className="flex min-h-8 items-center">
                  <Space wrap>
                    <Checkbox
                      checked={form.featureTeamManagement}
                      onChange={(event) => setForm((prev) => ({ ...prev, featureTeamManagement: event.target.checked }))}
                    >
                      {t("adminPlans.featureTeamManagement")}
                    </Checkbox>
                    <Checkbox
                      checked={form.featureApiAccess}
                      onChange={(event) => setForm((prev) => ({ ...prev, featureApiAccess: event.target.checked }))}
                    >
                      {t("adminPlans.featureApiAccess")}
                    </Checkbox>
                    <Checkbox
                      checked={form.featurePrivateDeployment}
                      onChange={(event) => setForm((prev) => ({ ...prev, featurePrivateDeployment: event.target.checked }))}
                    >
                      {t("adminPlans.featurePrivateDeployment")}
                    </Checkbox>
                  </Space>
                </div>
              </Col>
            </Row>
          </section>

          <section>
            <p className="mb-1 text-sm font-semibold text-[#111827]">{t("adminPlans.section4Title")}</p>
            <Text type="secondary" className="mb-3 block text-xs">{t("adminPlans.section4Subtitle")}</Text>
            <div className="mb-3">
              <Checkbox
                checked={form.allExperts}
                onChange={(event) => setForm((prev) => ({ ...prev, allExperts: event.target.checked }))}
              >
                <span className="font-medium">{t("adminPlans.allExpertsLabel")}</span>
                <span className="ml-2 text-xs text-[#8a8f98]">{t("adminPlans.allExpertsHint")}</span>
              </Checkbox>
            </div>
            {!form.allExperts && experts.length ? (
              <div className="max-h-[260px] overflow-auto pr-1">
                <Row gutter={[12, 12]}>
                  {experts.map((expert) => {
                    const active = form.expertIds.includes(expert.id);
                    return (
                      <Col key={expert.id} span={12}>
                        <label
                          className={`flex cursor-pointer items-start gap-3 rounded-[10px] border p-3 ${
                            active ? "border-[#8ab4ff] bg-[#eef5ff]" : "border-[#e2e5ea] hover:bg-[#f8fafc]"
                          }`}
                        >
                          <Checkbox
                            checked={active}
                            disabled={referencesLoading}
                            onChange={() => toggleExpert(expert.id)}
                            className="mt-1"
                          />
                          <span className="min-w-0">
                            <strong className="block text-sm text-[#374151]">{expert.name}</strong>
                            <small className="mt-1 block text-[#8a8f98]">{expert.abilityIntro}</small>
                          </span>
                        </label>
                      </Col>
                    );
                  })}
                </Row>
              </div>
            ) : !form.allExperts ? (
              <Text type="secondary" className="text-sm">
                {referencesLoading ? t("adminPlans.loadingExperts") : t("adminPlans.noExperts")}
              </Text>
            ) : null}
          </section>

          <Divider className="!my-0" />
          <Text type="secondary" className="text-sm">{t("adminPlans.footerNote")}</Text>
        </div>
      </Modal>
    </div>
  );
}
