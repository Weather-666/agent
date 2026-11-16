"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  DatePicker,
  Descriptions,
  Input,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { ArrowLeftOutlined, PlusOutlined } from "@ant-design/icons";
import { useI18n, type Translate } from "@/lib/i18n";
import { getPlans, type Plan } from "@/lib/api/admin-client";
import {
  createTenant,
  getTenant,
  getTenants,
  getTenantCredits,
  getTenantCreditLedger,
  createCreditAdjustment,
  updateTenantSubscription,
  type GetTenantsParams,
  type SubscriptionStatus,
  type Tenant,
  type TenantMember,
  type TenantType,
  type TenantCreditSummary,
  type TenantCreditLedgerEntry,
  type UpdateTenantSubscriptionParams,
} from "@/lib/api/admin-client";

const { Title, Text } = Typography;


type TenantTypeFilter = "all" | "personal" | "team";
type SubscriptionTypeFilter = "all" | "free" | "monthly" | "yearly" | "sales";
type SubscriptionStatusFilter = "all" | "active" | "expiring_soon" | "expired" | "trialing" | "past_due" | "cancelled";

const SUBSCRIPTION_TYPE_VALUES: SubscriptionTypeFilter[] = ["all", "free", "monthly", "yearly", "sales"];

const PAGE_SIZE = 20;

function getSubscriptionStatusOptions(t: Translate): Array<{ value: SubscriptionStatusFilter; label: string }> {
  return [
    { value: "all", label: t("adminTenants.allSubscriptionStatus") },
    { value: "active", label: t("adminTenants.statusActive") },
    { value: "expiring_soon", label: t("adminTenants.statusExpiringSoon") },
    { value: "expired", label: t("adminTenants.statusExpired") },
    { value: "trialing", label: t("adminTenants.statusTrialing") },
    { value: "past_due", label: t("adminTenants.statusPastDue") },
    { value: "cancelled", label: t("adminTenants.statusCancelled") },
  ];
}

function getSubscriptionTypeOptions(t: Translate): Array<{ value: SubscriptionTypeFilter; label: string }> {
  return [
    { value: "all", label: t("adminTenants.allSubscriptionTypes") },
    { value: "free", label: t("adminTenants.billingFree") },
    { value: "monthly", label: t("adminTenants.billingMonthly") },
    { value: "yearly", label: t("adminTenants.billingYearly") },
    { value: "sales", label: t("adminTenants.billingSales") },
  ];
}

function formatDate(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
}

function formatMoney(cents?: number | null) {
  if (!cents) return "¥0";
  return `¥${(cents / 100).toLocaleString("zh-CN")}`;
}

function formatNumber(value?: number | null) {
  if (typeof value !== "number") return "-";
  return value.toLocaleString("zh-CN");
}

function getUsagePercent(used?: number | null, limit?: number | null) {
  if (!limit || typeof used !== "number") return 0;
  return Math.min(Math.round((used / limit) * 100), 100);
}

function tenantTypeLabel(type: TenantType | null | undefined, t: Translate) {
  return type === "personal" ? t("adminTenants.typePersonal") : t("adminTenants.typeTeam");
}

function billingPeriodLabel(value: string | null | undefined, t: Translate) {
  if (value === "free") return t("adminTenants.billingFree");
  if (value === "monthly") return t("adminTenants.billingMonthly");
  if (value === "yearly") return t("adminTenants.billingYearly");
  if (value === "sales") return t("adminTenants.billingSales");
  return value || "-";
}

function subscriptionTypeLabel(tenant: Tenant, t: Translate) {
  const planName = tenant.currentSubscription?.planName || tenant.currentPlan?.name || "-";
  const period = tenant.currentSubscription?.billingPeriod || tenant.currentPlan?.billingPeriod;
  return period ? `${planName} · ${billingPeriodLabel(period, t)}` : planName;
}

function subscriptionStatusLabel(status: string | null | undefined, t: Translate) {
  if (status === "active") return t("adminTenants.statusActive");
  if (status === "expiring_soon") return t("adminTenants.statusExpiringSoon");
  if (status === "expired") return t("adminTenants.statusExpired");
  if (status === "trialing") return t("adminTenants.statusTrialing");
  if (status === "past_due") return t("adminTenants.statusPastDue");
  if (status === "cancelled") return t("adminTenants.statusCancelled");
  return status || "-";
}

function statusTag(status: SubscriptionStatus | null | undefined, t: Translate) {
  if (status === "active" || status === "trialing") {
    return <Tag color="green">{subscriptionStatusLabel(status, t)}</Tag>;
  }
  if (status === "expiring_soon" || status === "past_due") {
    return <Tag color="gold">{subscriptionStatusLabel(status, t)}</Tag>;
  }
  if (status === "expired" || status === "cancelled") {
    return <Tag color="red">{subscriptionStatusLabel(status, t)}</Tag>;
  }
  return <Tag>{subscriptionStatusLabel(status, t)}</Tag>;
}

function tenantTypeTag(type: TenantType | null | undefined, t: Translate) {
  if (type === "personal") {
    return <Tag color="gold">{t("adminTenants.typePersonal")}</Tag>;
  }
  return <Tag color="geekblue">{t("adminTenants.typeTeam")}</Tag>;
}

function memberRoleLabel(role: TenantMember["role"] | undefined, t: Translate) {
  if (role === "owner") return t("adminTenants.roleOwner");
  if (role === "admin") return t("adminTenants.roleAdmin");
  if (role === "member") return t("adminTenants.roleMember");
  return role || "-";
}

function getErrorMessage(error: unknown, t: Translate) {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string") return message;
  }
  return t("adminTenants.errorGeneric");
}

function UsageBar({ used, limit, label }: { used?: number | null; limit?: number | null; label: string }) {
  const percent = getUsagePercent(used, limit);
  const strokeColor = percent >= 90 ? "#d94848" : percent >= 75 ? "#d98b21" : "#1d4ed8";

  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-3 text-xs text-[#626872]">
        <span>{label}</span>
        <span>{formatNumber(used)} / {formatNumber(limit)}</span>
      </div>
      <Progress percent={percent} strokeColor={strokeColor} size="small" showInfo={false} />
    </div>
  );
}

type OrderRow = NonNullable<NonNullable<Tenant["orderSummary"]>["recentOrders"]>[number];

function TenantDetailPage({ tenant, onBack }: { tenant: Tenant; onBack: () => void }) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const credits = tenant.monthlyCredits;
  const subscription = tenant.currentSubscription;
  const plan = tenant.currentPlan;
  const orderSummary = tenant.orderSummary;
  const creditsRemaining = credits?.remainingCredits ?? 0;
  const showMembersOverview = tenant.type === "team";
  const owner = tenant.members?.find((member) => member.role === "owner");

  const [creditSummary, setCreditSummary] = useState<TenantCreditSummary | null>(null);
  const [ledger, setLedger] = useState<TenantCreditLedgerEntry[]>([]);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [creditSectionLoaded, setCreditSectionLoaded] = useState(false);
  const [adjustCreditOpen, setAdjustCreditOpen] = useState(false);
  const [adjustCreditForm, setAdjustCreditForm] = useState({ amount: "", reason: "" });
  const [adjustCreditSubmitting, setAdjustCreditSubmitting] = useState(false);

  const orderColumns: TableColumnsType<OrderRow> = [
    { title: t("adminTenants.colOrderNo"), key: "orderNo", render: (_, order) => order.orderNo || "-" },
    { title: t("adminTenants.planPeriod"), key: "plan", render: (_, order) => `${order.planName || "-"} / ${billingPeriodLabel(order.billingPeriod, t)}` },
    { title: t("adminTenants.colAmount"), key: "amount", render: (_, order) => formatMoney(order.amountCents) },
    { title: t("adminTenants.colTime"), key: "time", render: (_, order) => formatDate(order.paidAt) },
    { title: t("adminTenants.colStatus"), key: "status", render: (_, order) => <Tag color="green">{order.status || "-"}</Tag> },
  ];

  const summaryStats = [
    { label: t("adminTenants.tenantType"), value: tenantTypeLabel(tenant.type, t), note: tenant.type === "personal" ? t("adminTenants.personalAutoCreated") : t("adminTenants.teamMemberCount", { count: tenant.memberCount }) },
    { label: t("adminTenants.monthlyCredits"), value: formatNumber(credits?.deductedCredits) + " / " + formatNumber(credits?.monthlyCreditLimit), note: t("adminTenants.creditsRemaining", { count: formatNumber(creditsRemaining) }) },
    { label: t("adminTenants.totalSpending"), value: formatMoney(orderSummary?.totalAmountCents), note: t("adminTenants.orderCountSummary", { count: orderSummary?.orderCount ?? 0 }) },
  ];

  async function loadCreditSection(page = 1) {
    if (!creditSectionLoaded) setCreditSectionLoaded(true);
    setLedgerLoading(true);
    try {
      const [summaryRes, ledgerRes] = await Promise.all([
        getTenantCredits(tenant.id),
        getTenantCreditLedger(tenant.id, { page, pageSize: 10 }),
      ]);
      setCreditSummary(summaryRes);
      setLedger(Array.isArray(ledgerRes.items) ? ledgerRes.items : []);
      setLedgerTotal(ledgerRes.total ?? 0);
      setLedgerPage(page);
    } catch {
      message.error("积分数据加载失败");
    } finally {
      setLedgerLoading(false);
    }
  }

  function generateIdempotencyKey() {
    const ts = Date.now().toString(36);
    const rand = Math.random().toString(36).slice(2, 8);
    return `admin-adj-${ts}-${rand}`;
  }

  async function handleCreditAdjust() {
    const amount = Number(adjustCreditForm.amount);
    if (!Number.isFinite(amount) || amount === 0) {
      message.error("请输入有效的积分数量（非零整数）");
      return;
    }
    if (!adjustCreditForm.reason.trim()) {
      message.error("请输入调整原因");
      return;
    }
    setAdjustCreditSubmitting(true);
    try {
      await createCreditAdjustment(
        tenant.id,
        { amount, reason: adjustCreditForm.reason.trim() },
        generateIdempotencyKey()
      );
      message.success("积分调整成功");
      setAdjustCreditOpen(false);
      setAdjustCreditForm({ amount: "", reason: "" });
      void loadCreditSection(1);
    } catch (err) {
      message.error(err && typeof err === "object" && "message" in err ? String((err as { message: unknown }).message) : "积分调整失败");
    } finally {
      setAdjustCreditSubmitting(false);
    }
  }

  return (
    <div className="grid min-w-0 gap-[18px]">
      <Button className="w-fit" icon={<ArrowLeftOutlined />} onClick={onBack}>{t("adminTenants.backToList")}</Button>

      <Card>
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <Title level={3} className="!mb-0">{tenant.name}</Title>
            <Space size={[8, 8]} wrap className="mt-2">
              {tenantTypeTag(tenant.type, t)}
              <Tag color="geekblue">{subscriptionTypeLabel(tenant, t)}</Tag>
              {statusTag(subscription?.status, t)}
            </Space>
            <p className="mt-3 text-sm text-[#6b7280]">
              {t("adminTenants.tenantMetaLine", { id: tenant.id, slug: tenant.slug, date: formatDate(tenant.createdAt) })}
            </p>
          </div>
          <div className="rounded-[8px] border border-[#e6e6e3] bg-[#fbfbfa] px-4 py-3 text-sm text-[#374151]">
            <div className="text-xs text-[#8a8f98]">{t("adminTenants.ownerLabel")}</div>
            <strong className="mt-1 block text-[#111827]">{tenant.ownerUserName || "-"}</strong>
            <span className="mt-1 block text-xs text-[#626872]">{tenant.ownerUserEmail || "-"}</span>
          </div>
        </div>
      </Card>

      <Row gutter={[12, 12]}>
        {summaryStats.map((item) => (
          <Col key={item.label} xs={24} sm={12} md={8}>
            <Card size="small">
              <Text type="secondary" className="text-sm">{item.label}</Text>
              <strong className="mt-2 block text-2xl text-[#111827]">{item.value}</strong>
              <Text type="secondary" className="mt-1 block text-xs">{item.note}</Text>
            </Card>
          </Col>
        ))}
      </Row>

      <Row gutter={[18, 18]}>
        <Col xs={24} xl={16}>
          <div className="grid gap-[18px]">
            <Card title={t("adminTenants.currentSubscription")}>
              <Descriptions column={{ xs: 1, sm: 2 }} size="small">
                <Descriptions.Item label={t("adminTenants.planPeriod")}>
                  {subscription?.planName || plan?.name || "-"} / {billingPeriodLabel(subscription?.billingPeriod || plan?.billingPeriod, t)}
                </Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.price")}>{subscription?.priceLabel || plan?.priceLabel || "-"}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.subscriptionPeriod")}>
                  {formatDate(subscription?.currentPeriodStart)} - {formatDate(subscription?.currentPeriodEnd)}
                </Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.expiryReminder")}>
                  {typeof subscription?.daysUntilExpiry === "number"
                    ? subscription.daysUntilExpiry >= 0
                      ? t("adminTenants.daysRemaining", { days: subscription.daysUntilExpiry })
                      : t("adminTenants.daysExpired", { days: Math.abs(subscription.daysUntilExpiry) })
                    : "-"}
                </Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.subscriptionStatus")}>{statusTag(subscription?.status, t)}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.autoRenew")}>
                  {subscription?.autoRenew ? t("adminTenants.autoRenewOn") : t("adminTenants.autoRenewOff")}
                </Descriptions.Item>
              </Descriptions>
            </Card>

            <Card title={t("adminTenants.tenantInfo")}>
              <Descriptions column={{ xs: 1, sm: 2 }} size="small">
                <Descriptions.Item label={t("adminTenants.tenantId")}>{tenant.id}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.tenantType")}>{tenantTypeLabel(tenant.type, t)}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.tenantSlug")}>{tenant.slug}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.ownerLabel")}>{tenant.ownerUserName || "-"}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.ownerEmail")}>{tenant.ownerUserEmail || "-"}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.createdAt")}>{formatDate(tenant.createdAt)}</Descriptions.Item>
                <Descriptions.Item label={t("adminTenants.updatedAt")}>{formatDate(tenant.updatedAt)}</Descriptions.Item>
              </Descriptions>
            </Card>

            <Card title={t("adminTenants.orderRecords")}>
              <Table<OrderRow>
                rowKey={(order) => order.orderNo || String(order.paidAt)}
                columns={orderColumns}
                dataSource={orderSummary?.recentOrders ?? []}
                size="small"
                scroll={{ x: 620 }}
                locale={{ emptyText: t("adminTenants.noOrders") }}
                pagination={false}
              />
            </Card>
          </div>
        </Col>

        <Col xs={24} xl={8}>
          <div className="grid content-start gap-[18px]">
            <Card
              title={t("adminTenants.monthlyCredits")}
              extra={
                <Button size="small" onClick={() => void loadCreditSection(1)}>
                  {creditSectionLoaded ? t("adminTenants.refresh") : t("adminTenants.loadCredits")}
                </Button>
              }
            >
              <div className="grid gap-4">
                <UsageBar
                  used={creditSummary?.deductedCredits ?? credits?.deductedCredits}
                  limit={creditSummary?.monthlyCreditLimit ?? credits?.monthlyCreditLimit}
                  label={t("adminTenants.usageCredits")}
                />
                {creditSummary && (
                  <div className="grid grid-cols-2 gap-2 text-xs text-[#626872]">
                    <div>估算已用: <strong>{formatNumber(creditSummary.estimatedUsedCredits)}</strong></div>
                    <div>实际扣除: <strong>{formatNumber(creditSummary.deductedCredits)}</strong></div>
                    <div>剩余额度: <strong>{formatNumber(creditSummary.remainingCredits)}</strong></div>
                    {typeof creditSummary.ledgerBalance === "number" && (
                      <div>账本余额: <strong>{formatNumber(creditSummary.ledgerBalance)}</strong></div>
                    )}
                    {!creditSummary.enforcementEnabled && (
                      <div className="col-span-2 text-[#8a8f98]">积分限额暂不强制执行</div>
                    )}
                  </div>
                )}
                <Button size="small" type="primary" onClick={() => setAdjustCreditOpen(true)}>
                  手动调整积分
                </Button>
              </div>
            </Card>

            {showMembersOverview ? (
              <Card title={t("adminTenants.membersOverview")}>
                <div className="grid gap-3">
                  {tenant.members?.length ? (
                    tenant.members.map((member) => (
                      <div key={member.userId} className="rounded-[8px] border border-[#e6e6e3] p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <strong className="block text-sm text-[#111827]">{member.name || member.email}</strong>
                            <p className="mt-1 text-xs text-[#8a8f98]">{member.email}</p>
                          </div>
                          <Tag color="geekblue">{memberRoleLabel(member.role, t)}</Tag>
                        </div>
                        <p className="mt-2 text-xs text-[#626872]">{t("adminTenants.joinedAt", { date: formatDate(member.joinedAt) })}</p>
                      </div>
                    ))
                  ) : (
                    <Text type="secondary" className="text-sm">{t("adminTenants.noMembers")}</Text>
                  )}
                </div>
              </Card>
            ) : (
              <Card title={t("adminTenants.personalWorkspace")}>
                <div className="rounded-[8px] border border-[#e6e6e3] p-3">
                  <span className="text-xs text-[#8a8f98]">{t("adminTenants.roleOwner")}</span>
                  <strong className="mt-1 block text-sm text-[#111827]">{owner?.name || tenant.ownerUserName || "-"}</strong>
                  <p className="mt-1 text-xs text-[#626872]">{owner?.email || tenant.ownerUserEmail || "-"}</p>
                </div>
              </Card>
            )}

            {creditSectionLoaded && (
              <Card
                title="积分明细"
                size="small"
                loading={ledgerLoading}
              >
                <Table<TenantCreditLedgerEntry>
                  rowKey="id"
                  size="small"
                  dataSource={ledger}
                  scroll={{ x: 400 }}
                  pagination={{
                    current: ledgerPage,
                    pageSize: 10,
                    total: ledgerTotal,
                    showSizeChanger: false,
                    onChange: (page) => void loadCreditSection(page),
                  }}
                  columns={[
                    {
                      title: "类型",
                      key: "type",
                      render: (_, entry) => {
                        const labels: Record<string, string> = {
                          monthly_grant: "月度赠送",
                          upgrade_grant: "升级赠送",
                          turn_charge: "对话扣费",
                          manual_adjustment: "手动调整",
                        };
                        return <Tag>{labels[entry.entryType] ?? entry.entryType}</Tag>;
                      },
                    },
                    {
                      title: "金额",
                      key: "amount",
                      render: (_, entry) => (
                        <span className={entry.amount >= 0 ? "text-green-600" : "text-red-600"}>
                          {entry.amount >= 0 ? "+" : ""}{formatNumber(entry.amount)}
                        </span>
                      ),
                    },
                    { title: "原因", key: "reason", render: (_, entry) => entry.reason || "-" },
                    { title: "时间", key: "createdAt", render: (_, entry) => formatDate(entry.createdAt) },
                  ]}
                  locale={{ emptyText: "暂无积分记录" }}
                />
              </Card>
            )}
          </div>
        </Col>
      </Row>

      <Modal
        open={adjustCreditOpen}
        title="手动调整积分"
        onCancel={() => { setAdjustCreditOpen(false); setAdjustCreditForm({ amount: "", reason: "" }); }}
        onOk={handleCreditAdjust}
        confirmLoading={adjustCreditSubmitting}
        okText="确认调整"
        cancelText="取消"
      >
        <div className="mt-4 grid gap-4">
          <div>
            <label className="mb-1 block text-sm text-[#374151]">积分数量（正数为增加，负数为扣减）</label>
            <Input
              type="number"
              value={adjustCreditForm.amount}
              onChange={(e) => setAdjustCreditForm((prev) => ({ ...prev, amount: e.target.value }))}
              placeholder="如：100 或 -50"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-[#374151]">调整原因（必填）</label>
            <Input.TextArea
              rows={3}
              value={adjustCreditForm.reason}
              onChange={(e) => setAdjustCreditForm((prev) => ({ ...prev, reason: e.target.value }))}
              placeholder="请说明调整原因，如：活动补偿、客服调整等"
            />
          </div>
          <Text type="secondary" className="text-xs">
            系统将自动生成唯一幂等键以防止重复提交
          </Text>
        </div>
      </Modal>
    </div>
  );
}

export default function TenantsPage() {
  const { t } = useI18n();
  const { message } = App.useApp();
  const searchParams = useSearchParams();
  const subscriptionTypeParam = searchParams.get("subscriptionType");
  const initialSubscriptionType: SubscriptionTypeFilter = SUBSCRIPTION_TYPE_VALUES.includes(
    subscriptionTypeParam as SubscriptionTypeFilter
  )
    ? (subscriptionTypeParam as SubscriptionTypeFilter)
    : "all";
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [keyword, setKeyword] = useState("");
  const [tenantType, setTenantType] = useState<TenantTypeFilter>("all");
  const [subscriptionType, setSubscriptionType] = useState<SubscriptionTypeFilter>(initialSubscriptionType);
  const [subscriptionStatus, setSubscriptionStatus] = useState<SubscriptionStatusFilter>("all");
  const [detailTenant, setDetailTenant] = useState<Tenant | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const [plans, setPlans] = useState<Plan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [adjustModalTenantId, setAdjustModalTenantId] = useState("");
  const [adjustModalOpen, setAdjustModalOpen] = useState(false);
  const [adjustSubmitting, setAdjustSubmitting] = useState(false);
  const [adjustForm, setAdjustForm] = useState<{
    planId: string;
    billingPeriod: string;
    status: string;
    currentPeriodStart: string;
    currentPeriodEnd: string;
    cancelAtPeriodEnd: boolean;
  }>({
    planId: "",
    billingPeriod: "free",
    status: "active",
    currentPeriodStart: "",
    currentPeriodEnd: "",
    cancelAtPeriodEnd: false,
  });
  const plansLoadedRef = useRef(false);

  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createForm, setCreateForm] = useState({ name: "", slug: "", ownerUserId: "" });

  const loadTenants = useCallback(async () => {
    setIsLoading(true);
    const params: GetTenantsParams = {
      page,
      pageSize,
    };
    if (keyword.trim()) params.search = keyword.trim();
    if (tenantType !== "all") params.type = tenantType;
    if (subscriptionType !== "all") params.subscriptionType = subscriptionType;
    if (subscriptionStatus !== "all") params.subscriptionStatus = subscriptionStatus;

    try {
      const response = await getTenants(params);
      setTenants(Array.isArray(response.items) ? response.items : []);
      setTotal(response.total ?? 0);
    } catch (err) {
      setTenants([]);
      setTotal(0);
      message.error(getErrorMessage(err, t));
    } finally {
      setIsLoading(false);
    }
  }, [keyword, page, pageSize, subscriptionStatus, subscriptionType, tenantType, t, message]);

  useEffect(() => {
    void Promise.resolve().then(loadTenants);
  }, [loadTenants]);

  const summary = useMemo(() => {
    const activeCount = tenants.filter((tenant) => tenant.currentSubscription?.status === "active").length;
    const expiringCount = tenants.filter((tenant) => tenant.currentSubscription?.status === "expiring_soon").length;
    const personalCount = tenants.filter((tenant) => tenant.type === "personal").length;
    const teamCount = tenants.filter((tenant) => tenant.type === "team").length;

    return [
      { label: t("adminTenants.summaryPageTenants"), value: tenants.length },
      { label: t("adminTenants.typePersonal"), value: personalCount },
      { label: t("adminTenants.typeTeam"), value: teamCount },
      { label: t("adminTenants.statusActive"), value: activeCount },
      { label: t("adminTenants.statusExpiringSoon"), value: expiringCount },
    ];
  }, [tenants, t]);

  function openCreateModal() {
    setCreateForm({ name: "", slug: "", ownerUserId: "" });
    setCreateModalOpen(true);
  }

  async function handleCreateSubmit() {
    const name = createForm.name.trim();
    const ownerUserId = createForm.ownerUserId.trim();

    if (!name) {
      message.error(t("adminTenants.fieldTenantNameRequired"));
      return;
    }
    if (!ownerUserId) {
      message.error(t("adminTenants.fieldOwnerUserIdRequired"));
      return;
    }

    setCreateSubmitting(true);
    try {
      await createTenant({
        name,
        ownerUserId,
        slug: createForm.slug.trim() || undefined,
      });
      message.success(t("adminTenants.createTenantSuccess"));
      setCreateModalOpen(false);
      void loadTenants();
    } catch (err) {
      message.error(getErrorMessage(err, t));
    } finally {
      setCreateSubmitting(false);
    }
  }

  async function openDetail(tenantId: string) {
    try {
      setDetailTenant(await getTenant(tenantId));
    } catch (err) {
      message.error(getErrorMessage(err, t));
    }
  }

  async function openAdjustModal(tenant: Tenant) {
    setAdjustModalTenantId(tenant.id);
    const sub = tenant.currentSubscription;
    setAdjustForm({
      planId: sub?.planId || "",
      billingPeriod: sub?.billingPeriod || "free",
      status: sub?.status || "active",
      currentPeriodStart: sub?.currentPeriodStart ? dayjs(sub.currentPeriodStart).format("YYYY-MM-DD") : "",
      currentPeriodEnd: sub?.currentPeriodEnd ? dayjs(sub.currentPeriodEnd).format("YYYY-MM-DD") : "",
      cancelAtPeriodEnd: sub?.cancelAtPeriodEnd || false,
    });
    setAdjustModalOpen(true);
    if (!plansLoadedRef.current) {
      setPlansLoading(true);
      try {
        const res = await getPlans();
        setPlans(Array.isArray(res.items) ? res.items : []);
        plansLoadedRef.current = true;
      } catch {
        message.error(t("adminTenants.loadPlansFailed"));
      } finally {
        setPlansLoading(false);
      }
    }
  }

  async function handleAdjustSubmit() {
    if (!adjustForm.planId) {
      message.error(t("adminTenants.selectPlanRequired"));
      return;
    }
    setAdjustSubmitting(true);
    try {
      const payload: UpdateTenantSubscriptionParams = {
        planId: adjustForm.planId,
        billingPeriod: adjustForm.billingPeriod as UpdateTenantSubscriptionParams["billingPeriod"],
        status: adjustForm.status as UpdateTenantSubscriptionParams["status"],
        cancelAtPeriodEnd: adjustForm.cancelAtPeriodEnd,
      };
      if (adjustForm.currentPeriodStart) payload.currentPeriodStart = adjustForm.currentPeriodStart;
      if (adjustForm.currentPeriodEnd) payload.currentPeriodEnd = adjustForm.currentPeriodEnd;
      await updateTenantSubscription(adjustModalTenantId, payload);
      message.success(t("adminTenants.planAdjusted"));
      setAdjustModalOpen(false);
      void loadTenants();
    } catch (err) {
      message.error(getErrorMessage(err, t));
    } finally {
      setAdjustSubmitting(false);
    }
  }

  if (detailTenant) {
    return <TenantDetailPage tenant={detailTenant} onBack={() => setDetailTenant(null)} />;
  }

  const subscriptionStatusOptions = getSubscriptionStatusOptions(t);
  const subscriptionTypeOptions = getSubscriptionTypeOptions(t);

  const columns: TableColumnsType<Tenant> = [
    {
      title: t("adminTenants.colTenant"),
      key: "tenant",
      render: (_, tenant) => (
        <div>
          <div className="font-medium text-[#111827]">{tenant.name}</div>
          <div className="mt-1 text-xs text-[#8a8f98]">{tenant.slug}</div>
          <div className="mt-2 text-xs text-[#626872]">{tenant.ownerUserName || "-"} · {tenant.ownerUserEmail || "-"}</div>
        </div>
      ),
    },
    { title: t("adminTenants.tenantType"), key: "type", render: (_, tenant) => tenantTypeTag(tenant.type, t) },
    {
      title: t("adminTenants.colSubscriptionType"),
      key: "subType",
      render: (_, tenant) => (
        <div>
          <div>{subscriptionTypeLabel(tenant, t)}</div>
          <div className="mt-1 text-xs text-[#8a8f98]">
            {tenant.currentPlan?.name || tenant.currentSubscription?.planName || "-"} / {billingPeriodLabel(tenant.currentSubscription?.billingPeriod || tenant.currentPlan?.billingPeriod, t)}
          </div>
        </div>
      ),
    },
    { title: t("adminTenants.colSubscriptionStart"), key: "start", render: (_, tenant) => formatDate(tenant.currentSubscription?.currentPeriodStart) },
    {
      title: t("adminTenants.colExpiry"),
      key: "expiry",
      render: (_, tenant) => {
        const subscription = tenant.currentSubscription;
        return (
          <div>
            <div>{formatDate(subscription?.currentPeriodEnd)}</div>
            <div className="mt-1 text-xs text-[#8a8f98]">
              {typeof subscription?.daysUntilExpiry === "number"
                ? subscription.daysUntilExpiry >= 0
                  ? t("adminTenants.daysRemaining", { days: subscription.daysUntilExpiry })
                  : t("adminTenants.daysExpired", { days: Math.abs(subscription.daysUntilExpiry) })
                : "-"}
            </div>
          </div>
        );
      },
    },
    {
      title: t("adminTenants.monthlyCredits"),
      key: "usage",
      width: 220,
      render: (_, tenant) => (
        <div className="min-w-[160px]">
          <UsageBar used={tenant.monthlyCredits?.deductedCredits} limit={tenant.monthlyCredits?.monthlyCreditLimit} label={t("adminTenants.usageCredits")} />
        </div>
      ),
    },
    { title: t("adminTenants.subscriptionStatus"), key: "status", render: (_, tenant) => statusTag(tenant.currentSubscription?.status, t) },
    {
      title: t("adminTenants.autoRenew"),
      key: "autoRenew",
      render: (_, tenant) => (tenant.currentSubscription?.autoRenew ? t("adminTenants.autoRenewShortOn") : t("adminTenants.autoRenewShortOff")),
    },
    {
      title: t("adminUsers.colActions"),
      key: "actions",
      fixed: "right",
      width: 180,
      render: (_, tenant) => (
        <Space wrap>
          <Button size="small" onClick={() => void openDetail(tenant.id)}>{t("adminTenants.view")}</Button>
          <Button size="small" type="primary" onClick={() => void openAdjustModal(tenant)}>{t("adminTenants.adjustPlan")}</Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminUsers.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminUsers.pageTitleTenants")}</Title>
      </div>

      <Card className="min-w-0">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{t("adminTenants.tenantManagement")}</Title>
            <Text type="secondary" className="text-sm">{t("adminTenants.tenantManagementDesc")}</Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>{t("adminTenants.createTeamTenant")}</Button>
        </div>

        <div className="mb-5 flex flex-wrap gap-3">
          {summary.map((item) => (
            <div
              key={item.label}
              className="min-w-[140px] flex-1 rounded-[8px] border border-[#e6e6e3] bg-[#fbfbfa] px-4 py-3"
            >
              <div className="text-xs text-[#8a8f98]">{item.label}</div>
              <div className="mt-2 text-2xl font-semibold text-[#111827]">{item.value}</div>
            </div>
          ))}
        </div>

        <Space size="middle" wrap className="mb-4 w-full">
          <Input.Search
            allowClear
            value={keyword}
            onChange={(event) => {
              setPage(1);
              setKeyword(event.target.value);
            }}
            placeholder={t("adminTenants.searchPlaceholder")}
            style={{ width: 400 }}
          />
          <Select
            value={tenantType}
            onChange={(value) => {
              setPage(1);
              setTenantType(value);
            }}
            style={{ width: 180 }}
            options={[
              { value: "all", label: t("adminTenants.allTenantTypes") },
              { value: "personal", label: t("adminTenants.typePersonal") },
              { value: "team", label: t("adminTenants.typeTeam") },
            ]}
          />
          <Select
            value={subscriptionType}
            onChange={(value) => {
              setPage(1);
              setSubscriptionType(value);
            }}
            style={{ width: 200 }}
            options={subscriptionTypeOptions}
          />
          <Select
            value={subscriptionStatus}
            onChange={(value) => {
              setPage(1);
              setSubscriptionStatus(value);
            }}
            style={{ width: 200 }}
            options={subscriptionStatusOptions}
          />
        </Space>

        <Table<Tenant>
          rowKey="id"
          columns={columns}
          dataSource={tenants}
          loading={isLoading}
          scroll={{ x: 1280 }}
          locale={{ emptyText: t("adminTenants.noMatchingTenants") }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </Card>

      <Modal
        open={adjustModalOpen}
        title={t("adminTenants.adjustPlanTitle")}
        onCancel={() => setAdjustModalOpen(false)}
        onOk={handleAdjustSubmit}
        confirmLoading={adjustSubmitting}
        okText={t("adminTenants.adjustPlanConfirm")}
        cancelText={t("adminTenants.cancel")}
        width={480}
      >
        <div className="mt-4 grid gap-4">
          <div>
            <label className="mb-1 block text-sm text-[#374151]">{t("adminTenants.selectPlan")}</label>
            <Select
              className="w-full"
              loading={plansLoading}
              value={adjustForm.planId || undefined}
              onChange={(value) => setAdjustForm((prev) => ({ ...prev, planId: value }))}
              placeholder={t("adminTenants.selectPlanPlaceholder")}
              options={plans.map((plan) => ({ value: plan.id, label: `${plan.name} (${plan.code})` }))}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-[#374151]">{t("adminTenants.billingPeriod")}</label>
            <Select
              className="w-full"
              value={adjustForm.billingPeriod}
              onChange={(value) => setAdjustForm((prev) => ({ ...prev, billingPeriod: value }))}
              options={[
                { value: "free", label: t("adminTenants.billingFree") },
                { value: "monthly", label: t("adminTenants.billingMonthly") },
                { value: "yearly", label: t("adminTenants.billingYearly") },
                { value: "sales", label: t("adminTenants.billingSales") },
              ]}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-[#374151]">{t("adminTenants.subscriptionStatus")}</label>
            <Select
              className="w-full"
              value={adjustForm.status}
              onChange={(value) => setAdjustForm((prev) => ({ ...prev, status: value }))}
              options={[
                { value: "active", label: t("adminTenants.statusActive") },
                { value: "trialing", label: t("adminTenants.statusTrialing") },
                { value: "past_due", label: t("adminTenants.statusPastDue") },
                { value: "cancelled", label: t("adminTenants.statusCancelled") },
                { value: "expired", label: t("adminTenants.statusExpired") },
              ]}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-[#374151]">{t("adminTenants.subscriptionPeriod")}</label>
            <div className="flex gap-2">
              <DatePicker
                className="flex-1"
                placeholder={t("adminTenants.periodStartPlaceholder")}
                value={adjustForm.currentPeriodStart ? dayjs(adjustForm.currentPeriodStart) : null}
                disabledDate={(current) =>
                  !!adjustForm.currentPeriodEnd && current.isAfter(dayjs(adjustForm.currentPeriodEnd), "day")
                }
                onChange={(date: Dayjs | null) =>
                  setAdjustForm((prev) => ({ ...prev, currentPeriodStart: date ? date.format("YYYY-MM-DD") : "" }))
                }
              />
              <DatePicker
                className="flex-1"
                placeholder={t("adminTenants.periodEndPlaceholder")}
                value={adjustForm.currentPeriodEnd ? dayjs(adjustForm.currentPeriodEnd) : null}
                disabledDate={(current) =>
                  !!adjustForm.currentPeriodStart && current.isBefore(dayjs(adjustForm.currentPeriodStart), "day")
                }
                onChange={(date: Dayjs | null) =>
                  setAdjustForm((prev) => ({ ...prev, currentPeriodEnd: date ? date.format("YYYY-MM-DD") : "" }))
                }
              />
            </div>
          </div>
          <Checkbox
            checked={adjustForm.cancelAtPeriodEnd}
            onChange={(e) => setAdjustForm((prev) => ({ ...prev, cancelAtPeriodEnd: e.target.checked }))}
          >
            {t("adminTenants.cancelAtPeriodEnd")}
          </Checkbox>
        </div>
      </Modal>

      <Modal
        open={createModalOpen}
        title={t("adminTenants.createTeamTenant")}
        onCancel={() => setCreateModalOpen(false)}
        onOk={handleCreateSubmit}
        confirmLoading={createSubmitting}
        okText={t("adminTenants.createTenantConfirm")}
        cancelText={t("adminTenants.cancel")}
        width={480}
        destroyOnHidden
      >
        <div className="mt-4 grid gap-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-[#374151]">
              {t("adminTenants.fieldTenantName")}
              <span className="ml-1 text-red-500">*</span>
            </label>
            <Input
              value={createForm.name}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, name: e.target.value }))}
              placeholder={t("adminTenants.fieldTenantNamePlaceholder")}
              onPressEnter={handleCreateSubmit}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-[#374151]">
              {t("adminTenants.fieldOwnerUserId")}
              <span className="ml-1 text-red-500">*</span>
            </label>
            <Input
              value={createForm.ownerUserId}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, ownerUserId: e.target.value }))}
              placeholder={t("adminTenants.fieldOwnerUserIdPlaceholder")}
            />
            <p className="mt-1 text-xs text-[#8a8f98]">{t("adminTenants.fieldOwnerUserIdHint")}</p>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-[#374151]">
              {t("adminTenants.fieldTenantSlug")}
            </label>
            <Input
              value={createForm.slug}
              onChange={(e) => setCreateForm((prev) => ({ ...prev, slug: e.target.value }))}
              placeholder={t("adminTenants.fieldTenantSlugPlaceholder")}
            />
            <p className="mt-1 text-xs text-[#8a8f98]">{t("adminTenants.fieldTenantSlugHint")}</p>
          </div>
        </div>
      </Modal>
    </div>
  );
}
