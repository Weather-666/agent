"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Tabs,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { PlusOutlined } from "@ant-design/icons";
import {
  createExpertCategory,
  deleteExpertCategory,
  getExpertCategories,
  updateExpertCategory,
  type ExpertCategory,
} from "@/lib/api/admin-client";
import { getMcpConnectors, type McpConnector } from "@/lib/api/admin-client";
import {
  createExpert,
  deleteExpert as deleteExpertRequest,
  getExperts,
  updateExpert,
  updateExpertStatus,
  type Expert,
  type CreateExpertParams,
  type ExpertStatus,
  type MarketLabel,
  type UpdateExpertParams,
} from "@/lib/api/admin-client";
import { getKnowledgeBases, type KnowledgeBase } from "@/lib/api/admin-client";
import { getSkills, type Skill } from "@/lib/api/admin-client";
import { useI18n } from "@/lib/i18n";
import {
  emptyFormValues,
  getErrorMessage,
  getKbLabel,
  getSkillId,
  getSkillLabel,
  normalizeList,
  statusTagColor,
  STATUS_VALUES,
  type ExpertFormValues,
} from "./_helpers";

const { Title, Text, Paragraph } = Typography;

export default function AdminExpertsPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const [form] = Form.useForm<ExpertFormValues>();

  const statusLabelMap: Record<ExpertStatus, string> = {
    published: t("adminExperts.statusPublished"),
    draft: t("adminExperts.statusDraft"),
    unlisted: t("adminExperts.statusUnlisted"),
  };
  const statusOptions = STATUS_VALUES.map((value) => ({ value, label: statusLabelMap[value] }));
  const createStatusOptions = statusOptions.filter((item) => item.value !== "unlisted");

  const [experts, setExperts] = useState<Expert[]>([]);
  const [expertCategories, setExpertCategories] = useState<ExpertCategory[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [keyword, setKeyword] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingExpertId, setEditingExpertId] = useState("");
  const [referencesLoading, setReferencesLoading] = useState(true);
  const [expertsLoading, setExpertsLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pendingExpertId, setPendingExpertId] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const [categorySubmitting, setCategorySubmitting] = useState(false);
  const [contentLanguage, setContentLanguage] = useState<"zh" | "en">("zh");
  const [editingCategoryId, setEditingCategoryId] = useState("");
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [mcpConnectors, setMcpConnectors] = useState<McpConnector[]>([]);

  const getSkillLabelById = useCallback((skillId: string) => {
    const skill = skills.find((item) => getSkillId(item) === skillId || item.slug === skillId);
    return skill ? getSkillLabel(skill) : skillId;
  }, [skills]);

  useEffect(() => {
    let ignore = false;

    Promise.all([
      getExperts().catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminExperts.loadFailed")));
        return { items: [] };
      }),
      getExpertCategories().catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminExperts.categoriesLoadFailed")));
        return { items: [] };
      }),
      getKnowledgeBases().catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminExperts.knowledgeLoadFailed")));
        return { items: [] };
      }),
      getSkills({ limit: 100, offset: 0 }).catch((err) => {
        if (!ignore) message.error(getErrorMessage(err, t("adminExperts.skillsLoadFailed")));
        return { items: [] };
      }),
      getMcpConnectors().catch(() => ({ items: [] })),
    ])
      .then(([expertsResponse, categoriesResponse, knowledgeResponse, skillsResponse, mcpConnectorsResponse]) => {
        if (ignore) return;
        setExperts(Array.isArray(expertsResponse.items) ? expertsResponse.items : []);
        setExpertCategories(Array.isArray(categoriesResponse.items) ? categoriesResponse.items : []);
        setKnowledgeBases(Array.isArray(knowledgeResponse.items) ? knowledgeResponse.items : []);
        setSkills(Array.isArray(skillsResponse.items) ? skillsResponse.items : []);
        setMcpConnectors(Array.isArray(mcpConnectorsResponse.items) ? mcpConnectorsResponse.items : []);
      })
      .finally(() => {
        if (!ignore) {
          setExpertsLoading(false);
          setReferencesLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
    // Runs once on mount; `t`/`message` are only used for fallback strings.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  const stats = useMemo(() => {
    const published = experts.filter((item) => item.status === "published").length;
    const draft = experts.filter((item) => item.status === "draft").length;
    const unlisted = experts.filter((item) => item.status === "unlisted").length;

    return [
      { key: "total", label: t("adminExperts.statsTotal"), value: experts.length },
      { key: "published", label: t("adminExperts.statusPublished"), value: published },
      { key: "draft", label: t("adminExperts.statusDraft"), value: draft },
      { key: "unlisted", label: t("adminExperts.statusUnlisted"), value: unlisted },
    ];
  }, [experts, t]);

  const filteredExperts = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLowerCase();

    return experts.filter((expert) => {
      const skillLabels = expert.skillIds.map((skillId) => getSkillLabelById(skillId));
      const matchKeyword =
        !normalizedKeyword ||
        [expert.name, expert.categoryName, expert.abilityIntro, ...skillLabels, ...expert.tags]
          .join(" ")
          .toLowerCase()
          .includes(normalizedKeyword);
      const matchCategory = !categoryFilter || expert.categoryId === categoryFilter;
      const matchStatus = !statusFilter || expert.status === statusFilter;

      return matchKeyword && matchCategory && matchStatus;
    });
  }, [categoryFilter, experts, getSkillLabelById, keyword, statusFilter]);

  // Local filtering / deletions can shrink the result set below the current
  // page, so clamp to the last valid page instead of landing on an empty one.
  // Filter changes reset the page to 1 directly in their onChange handlers.
  const currentPage = Math.min(page, Math.max(1, Math.ceil(filteredExperts.length / pageSize)));

  const pagedExperts = useMemo(
    () => filteredExperts.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [filteredExperts, currentPage, pageSize],
  );

  function closeModal() {
    setIsModalOpen(false);
    setEditingExpertId("");
    setNewCategoryName("");
    form.resetFields();
  }

  async function handleCreateCategory() {
    const name = newCategoryName.trim();
    if (!name) {
      message.error(t("adminExperts.categoryNameRequired"));
      return;
    }
    if (expertCategories.some((category) => category.name === name)) {
      message.error(t("adminExperts.categoryExists"));
      return;
    }

    setCategorySubmitting(true);

    try {
      const created = await createExpertCategory({ name });
      setExpertCategories((prev) => [...prev, created]);
      form.setFieldValue("categoryId", created.id);
      setNewCategoryName("");
    } catch (err) {
      message.error(getErrorMessage(err, t("adminExperts.createCategoryFailed")));
    } finally {
      setCategorySubmitting(false);
    }
  }

  function openCreateModal() {
    setEditingExpertId("");
    setNewCategoryName("");
    setContentLanguage("zh");
    form.setFieldsValue({
      ...emptyFormValues(),
      categoryId: expertCategories[0]?.id ?? "",
      skillIds: skills[0] ? [getSkillId(skills[0])] : [],
      knowledgeBaseId: knowledgeBases[0]?.id ?? "",
    });
    setIsModalOpen(true);
  }

  function openEditModal(expert: Expert) {
    if (expert.status === "published") return;
    setEditingExpertId(expert.id);
    setNewCategoryName("");
    setContentLanguage("zh");
    const zh = expert.localizedContent?.zh;
    const en = expert.localizedContent?.en;
    form.setFieldsValue({
      zhName: zh?.name ?? expert.name,
      enName: en?.name ?? "",
      zhIntro: zh?.abilityIntro ?? expert.abilityIntro,
      enIntro: en?.abilityIntro ?? "",
      zhCategoryName: zh?.categoryName ?? expert.categoryName,
      enCategoryName: en?.categoryName ?? "",
      categoryId: expert.categoryId,
      instructions: expert.instructions ?? "",
      tags: expert.tags.join(", "),
      skillIds: expert.skillIds,
      knowledgeBaseId: expert.knowledgeBaseIds[0] ?? "",
      guideQuestions: [expert.guideQuestions[0] ?? "", expert.guideQuestions[1] ?? "", expert.guideQuestions[2] ?? ""],
      zhCtaText: zh?.summonButtonText ?? expert.summonButtonText ?? "",
      enCtaText: en?.summonButtonText ?? "",
      hot: (expert.marketLabels ?? []).includes("hot"),
      mcpConnectorIds: expert.mcpConnectorIds ?? [],
    });
    setIsModalOpen(true);
  }

  async function handleSubmit() {
    let values: ExpertFormValues;
    try {
      const allValues = form.getFieldsValue(true) as ExpertFormValues;
      if (![allValues.zhName, allValues.enName, allValues.zhIntro, allValues.enIntro, allValues.zhCategoryName, allValues.enCategoryName].every((value) => value?.trim())) {
        message.error(t("adminExperts.localizationRequired"));
        return;
      }
      await form.validateFields();
      values = form.getFieldsValue(true) as ExpertFormValues;
    } catch {
      return;
    }

    const name = values.zhName.trim();
    const intro = values.zhIntro.trim();
    const englishName = values.enName.trim();
    const zhCtaText = values.zhCtaText?.trim() || `召唤${name}`;
    const enCtaText = values.enCtaText?.trim() || `Summon ${englishName}`;
    const localizedContent = {
      zh: { name, abilityIntro: intro, categoryName: values.zhCategoryName.trim(), summonButtonText: zhCtaText },
      en: { name: englishName, abilityIntro: values.enIntro.trim(), categoryName: values.enCategoryName.trim(), summonButtonText: enCtaText },
    };

    setSubmitting(true);

    const basePayload = {
      name,
      categoryId: values.categoryId,
      abilityIntro: intro,
      localizedContent,
      instructions: values.instructions?.trim() || undefined,
      tags: normalizeList(values.tags ?? ""),
      skillIds: values.skillIds ?? [],
      knowledgeBaseIds: [values.knowledgeBaseId],
      guideQuestions: (values.guideQuestions ?? []).map((question) => (question ?? "").trim()).filter(Boolean),
      marketLabels: values.hot ? (["hot"] as MarketLabel[]) : [],
      summonButtonText: zhCtaText,
      mcpConnectorIds: values.mcpConnectorIds ?? [],
    };

    try {
      const saved = editingExpertId
        ? await updateExpert(editingExpertId, basePayload satisfies UpdateExpertParams)
        : await createExpert({ ...basePayload } satisfies CreateExpertParams);

      setExperts((prev) => {
        if (!editingExpertId) return [saved, ...prev];
        return prev.map((expert) => (expert.id === saved.id ? saved : expert));
      });
      message.success(editingExpertId ? t("adminExperts.updatedMessage") : t("adminExperts.createdMessage"));
      closeModal();
    } catch (err) {
      message.error(getErrorMessage(err, editingExpertId ? t("adminExperts.updateFailed") : t("adminExperts.createFailed")));
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleStatus(expert: Expert) {
    const nextStatus: ExpertStatus = expert.status === "published" ? "unlisted" : "published";
    const publishKey = "expert-publish-status";
    setPendingExpertId(expert.id);

    if (nextStatus === "published") {
      message.loading({ content: "正在上架...", key: publishKey, duration: 0 });
    }

    try {
      const updated = await updateExpertStatus(expert.id, nextStatus);
      setExperts((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      if (nextStatus === "published") {
        message.success({ content: t("adminExperts.publishedMessage"), key: publishKey });
      } else {
        message.success(t("adminExperts.unlistedMessage"));
      }
    } catch (err) {
      if (nextStatus === "published") {
        const hasResponse = !!(err as { response?: unknown }).response;
        if (hasResponse) {
          message.error({ content: getErrorMessage(err, t("adminExperts.updateStatusFailed")), key: publishKey });
        } else {
          // Network interrupted — backend result unknown; do not retry automatically.
          message.warning({ content: "上架结果尚未确认，请刷新查看", key: publishKey });
        }
      } else {
        message.error(getErrorMessage(err, t("adminExperts.updateStatusFailed")));
      }
    } finally {
      setPendingExpertId("");
    }
  }

  async function deleteExpert(expert: Expert) {
    setPendingExpertId(expert.id);

    try {
      await deleteExpertRequest(expert.id);
      setExperts((prev) => prev.filter((item) => item.id !== expert.id));
      message.success(t("adminExperts.deletedMessage"));
    } catch (err) {
      message.error(getErrorMessage(err, t("adminExperts.deleteFailed")));
    } finally {
      setPendingExpertId("");
    }
  }

  function confirmToggleStatus(expert: Expert) {
    const isPublished = expert.status === "published";
    modal.confirm({
      title: isPublished ? t("adminExperts.unlistConfirmTitle") : t("adminExperts.listConfirmTitle"),
      content: isPublished
        ? t("adminExperts.unlistConfirm", { name: expert.name })
        : t("adminExperts.listConfirm", { name: expert.name }),
      okText: isPublished ? t("adminExperts.unlist") : t("adminExperts.list"),
      okButtonProps: isPublished ? { danger: true } : undefined,
      cancelText: t("adminExperts.cancel"),
      onOk: () => toggleStatus(expert),
    });
  }

  function confirmDelete(expert: Expert) {
    modal.confirm({
      title: t("adminExperts.deleteConfirmTitle"),
      content: t("adminExperts.deleteConfirm", { name: expert.name }),
      okText: t("adminExperts.delete"),
      okButtonProps: { danger: true },
      cancelText: t("adminExperts.cancel"),
      onOk: () => deleteExpert(expert),
    });
  }

  async function handleDeleteCategory(categoryId: string) {
    try {
      await deleteExpertCategory(categoryId);
      setExpertCategories((prev) => prev.filter((c) => c.id !== categoryId));
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 409) {
        message.error("分类正在使用中，无法删除");
      } else {
        message.error(getErrorMessage(err, "删除分类失败"));
      }
    }
  }

  async function handleSaveCategory(categoryId: string) {
    const name = editingCategoryName.trim();
    if (!name) return;
    try {
      const updated = await updateExpertCategory(categoryId, { name });
      setExpertCategories((prev) => prev.map((c) => (c.id === categoryId ? updated : c)));
      setEditingCategoryId("");
      setEditingCategoryName("");
    } catch (err) {
      message.error(getErrorMessage(err, "更新分类失败"));
    }
  }

  const columns: TableColumnsType<Expert> = [
    {
      title: t("adminExperts.colName"),
      key: "name",
      render: (_, expert) => (
        <div>
          <strong className="block text-[#111827]">{expert.name}</strong>
          <span className="mt-1 block max-w-[240px] truncate text-xs text-[#8a8f98]">{expert.abilityIntro}</span>
        </div>
      ),
    },
    {
      title: t("adminExperts.colCategory"),
      dataIndex: "categoryName",
      key: "categoryName",
    },
    {
      title: t("adminExperts.colSkills"),
      key: "skills",
      render: (_, expert) =>
        expert.skillIds.length ? (
          <Space size={[4, 4]} wrap>
            {expert.skillIds.map((skillId) => (
              <Tag key={skillId} className="!m-0">{getSkillLabelById(skillId)}</Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary" className="text-xs">{t("adminExperts.unbound")}</Text>
        ),
    },
    {
      title: t("adminExperts.colKnowledge"),
      key: "knowledge",
      render: (_, expert) => {
        const id = expert.knowledgeBaseIds[0];
        if (!id) return null;
        const knowledgeBase = knowledgeBases.find((item) => item.id === id);
        return <Tag color="geekblue">{knowledgeBase ? getKbLabel(knowledgeBase) : id}</Tag>;
      },
    },
    {
      title: "MCP信息",
      key: "mcp",
      render: (_, expert) => {
        const ids = expert.mcpConnectorIds ?? [];
        if (!ids.length) return <Text type="secondary" className="text-xs">{t("adminExperts.unbound")}</Text>;
        return (
          <Space size={[4, 4]} wrap>
            {ids.map((id) => {
              const connector = mcpConnectors.find((c) => c.id === id);
              return <Tag key={id} color="purple" className="!m-0">{connector ? connector.name : id}</Tag>;
            })}
          </Space>
        );
      },
    },
    {
      title: t("adminExperts.colGuide"),
      key: "guide",
      render: (_, expert) => expert.guideQuestions.length,
    },
    {
      title: t("adminExperts.colStatus"),
      key: "status",
      render: (_, expert) => <Tag color={statusTagColor[expert.status]}>{statusLabelMap[expert.status]}</Tag>,
    },
    {
      title: t("adminExperts.colActions"),
      key: "actions",
      render: (_, expert) => (
        <Space wrap>
          {expert.status !== "published" ? (
            <Button size="small" onClick={() => openEditModal(expert)}>
              {t("adminExperts.edit")}
            </Button>
          ) : null}
          <Button
            size="small"
            loading={pendingExpertId === expert.id}
            onClick={() => confirmToggleStatus(expert)}
          >
            {expert.status === "published" ? t("adminExperts.unlist") : t("adminExperts.list")}
          </Button>
          {expert.status !== "published" ? (
            <Button size="small" danger disabled={pendingExpertId === expert.id} onClick={() => confirmDelete(expert)}>
              {t("adminExperts.delete")}
            </Button>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminExperts.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminExperts.pageTitle")}</Title>
      </div>

      <Row gutter={[12, 12]}>
        {stats.map((item) => (
          <Col key={item.key} xs={12} md={6}>
            <Card size="small">
              <Text type="secondary" className="text-sm">{item.label}</Text>
              <strong className="mt-2 block text-2xl font-semibold text-[#111827]">{item.value.toLocaleString()}</strong>
            </Card>
          </Col>
        ))}
      </Row>

      <Card>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{t("adminExperts.listTitle")}</Title>
            <Text type="secondary" className="text-sm">{t("adminExperts.listDescription")}</Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
            {t("adminExperts.createExpert")}
          </Button>
        </div>

        <Space size="middle" wrap className="mb-4 w-full">
          <Input.Search
            allowClear
            value={keyword}
            onChange={(event) => {
              setKeyword(event.target.value);
              setPage(1);
            }}
            placeholder={t("adminExperts.searchPlaceholder")}
            style={{ width: 280 }}
          />
          <Select
            value={categoryFilter || undefined}
            onChange={(value) => {
              setCategoryFilter(value ?? "");
              setPage(1);
            }}
            allowClear
            placeholder={t("adminExperts.allCategories")}
            style={{ width: 180 }}
            options={expertCategories.map((category) => ({ value: category.id, label: category.name }))}
          />
          <Select
            value={statusFilter || undefined}
            onChange={(value) => {
              setStatusFilter(value ?? "");
              setPage(1);
            }}
            allowClear
            placeholder={t("adminExperts.allStatuses")}
            style={{ width: 180 }}
            options={statusOptions}
          />
        </Space>

        <Table<Expert>
          rowKey="id"
          columns={columns}
          dataSource={pagedExperts}
          loading={expertsLoading}
          scroll={{ x: 1000 }}
          locale={{ emptyText: t("adminExperts.noMatch") }}
          pagination={{
            current: currentPage,
            pageSize,
            total: filteredExperts.length,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (total) => t("adminExperts.paginationTotal", { total }),
            onChange: (nextPage, nextPageSize) => {
              setPage(nextPage);
              setPageSize(nextPageSize);
            },
          }}
        />
      </Card>

      <Modal
        open={isModalOpen}
        title={editingExpertId ? t("adminExperts.editExpert") : t("adminExperts.createExpert")}
        width={860}
        onCancel={closeModal}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={t("adminExperts.save")}
        cancelText={t("adminExperts.cancel")}
        forceRender
        mask={{ closable: false }}
      >
        <Form<ExpertFormValues> form={form} layout="vertical" className="mt-2" initialValues={emptyFormValues()}>
          <p className="mb-3 mt-1 text-sm font-semibold text-[#111827]">{t("adminExperts.section1")}</p>
          <Tabs activeKey={contentLanguage} onChange={(key) => setContentLanguage(key as "zh" | "en")} items={[
            { key: "zh", label: t("adminExperts.contentChinese"), children: (
              <Row gutter={16}>
                <Col span={12}><Form.Item name="zhName" label={t("adminExperts.fieldName")}><Input placeholder={t("adminExperts.namePlaceholder")} /></Form.Item></Col>
                <Col span={12}><Form.Item name="zhCategoryName" label={t("adminExperts.fieldCategoryName")}><Input placeholder={t("adminExperts.categoryNamePlaceholder")} /></Form.Item></Col>
                <Col span={24}><Form.Item name="zhIntro" label={t("adminExperts.fieldIntro")}><Input.TextArea rows={3} placeholder={t("adminExperts.introPlaceholder")} /></Form.Item></Col>
              </Row>
            ) },
            { key: "en", label: t("adminExperts.contentEnglish"), children: (
              <Row gutter={16}>
                <Col span={12}><Form.Item name="enName" label={t("adminExperts.fieldName")}><Input placeholder={t("adminExperts.namePlaceholder")} /></Form.Item></Col>
                <Col span={12}><Form.Item name="enCategoryName" label={t("adminExperts.fieldCategoryName")}><Input placeholder={t("adminExperts.categoryNamePlaceholder")} /></Form.Item></Col>
                <Col span={24}><Form.Item name="enIntro" label={t("adminExperts.fieldIntro")}><Input.TextArea rows={3} placeholder={t("adminExperts.introPlaceholder")} /></Form.Item></Col>
              </Row>
            ) },
          ]} />
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="categoryId" label={t("adminExperts.fieldCategory")} rules={[{ required: true }]}>
                <Select
                  placeholder={t("adminExperts.selectCategory")}
                  options={expertCategories.map((category) => ({ value: category.id, label: category.name }))}
                  popupRender={(menu) => (
                    <>
                      {menu}
                      <Divider style={{ margin: "8px 0" }} />
                      <div style={{ padding: "0 8px 4px" }}>
                        <p className="mb-1 text-xs text-[#6b7280]">新增分类</p>
                        <Space.Compact style={{ width: "100%" }}>
                          <Input
                            value={newCategoryName}
                            onChange={(event) => setNewCategoryName(event.target.value)}
                            placeholder={t("adminExperts.newCategoryPlaceholder")}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                void handleCreateCategory();
                              }
                            }}
                          />
                          <Button type="primary" loading={categorySubmitting} onClick={() => void handleCreateCategory()}>
                            {t("adminExperts.add")}
                          </Button>
                        </Space.Compact>
                        {expertCategories.length > 0 && (
                          <>
                            <Divider style={{ margin: "8px 0" }} />
                            <p className="mb-1 text-xs text-[#6b7280]">管理分类</p>
                            <div className="max-h-[180px] overflow-y-auto">
                              {expertCategories.map((cat) => (
                                <div key={cat.id} className="flex items-center gap-1 py-1">
                                  {editingCategoryId === cat.id ? (
                                    <>
                                      <Input
                                        size="small"
                                        value={editingCategoryName}
                                        onChange={(e) => setEditingCategoryName(e.target.value)}
                                        onKeyDown={(e) => {
                                          if (e.key === "Enter") {
                                            e.preventDefault();
                                            void handleSaveCategory(cat.id);
                                          }
                                          if (e.key === "Escape") {
                                            setEditingCategoryId("");
                                            setEditingCategoryName("");
                                          }
                                        }}
                                        style={{ flex: 1 }}
                                      />
                                      <Button size="small" type="primary" onClick={() => void handleSaveCategory(cat.id)}>
                                        保存
                                      </Button>
                                      <Button size="small" onClick={() => { setEditingCategoryId(""); setEditingCategoryName(""); }}>
                                        取消
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <span className="flex-1 truncate text-sm">{cat.name}</span>
                                      <Button
                                        size="small"
                                        onClick={() => {
                                          setEditingCategoryId(cat.id);
                                          setEditingCategoryName(cat.name);
                                        }}
                                      >
                                        编辑
                                      </Button>
                                      <Button
                                        size="small"
                                        danger
                                        onClick={() => void handleDeleteCategory(cat.id)}
                                      >
                                        删除
                                      </Button>
                                    </>
                                  )}
                                </div>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                    </>
                  )}
                />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="instructions" label={t("adminExperts.fieldInstructions")}>
                <Input.TextArea rows={4} placeholder={t("adminExperts.instructionsPlaceholder")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tags" label={t("adminExperts.fieldTags")}>
                <Input placeholder={t("adminExperts.tagsPlaceholder")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="hot" label={t("adminExperts.fieldMarketHot")} valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <p className="mb-3 mt-5 text-sm font-semibold text-[#111827]">{t("adminExperts.section2")}</p>
          <Row>
            <Col span={16}>
              <Form.Item name="skillIds" extra={t("adminExperts.skillHint")}>
                <Select
                  mode="multiple"
                  allowClear
                  loading={referencesLoading}
                  placeholder={t("adminExperts.noSkills")}
                  options={skills.map((skill) => ({ value: getSkillId(skill), label: getSkillLabel(skill) }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <p className="mb-3 mt-5 text-sm font-semibold text-[#111827]">{t("adminExperts.section3")}</p>
          <Row>
            <Col span={12}>
              <Form.Item name="knowledgeBaseId" extra={t("adminExperts.knowledgeHint")} rules={[{ required: true }]}>
                <Select
                  loading={referencesLoading}
                  placeholder={t("adminExperts.noKnowledge")}
                  options={knowledgeBases.map((knowledgeBase) => ({ value: knowledgeBase.id, label: getKbLabel(knowledgeBase) }))}
                />
              </Form.Item>
            </Col>
          </Row>

          <p className="mb-3 mt-5 text-sm font-semibold text-[#111827]">{t("adminExperts.section4")}</p>
          <Paragraph type="secondary" className="!text-xs">{t("adminExperts.guideHint")}</Paragraph>
          <Row gutter={16}>
            {[0, 1, 2].map((index) => (
              <Col span={12} key={index}>
                <Form.Item
                  name={["guideQuestions", index]}
                  label={t("adminExperts.guideQuestionLabel", { index: index + 1 })}
                >
                  <Input
                    placeholder={
                      index === 0
                        ? t("adminExperts.guidePlaceholder1")
                        : index === 1
                          ? t("adminExperts.guidePlaceholder2")
                          : t("adminExperts.guidePlaceholder3")
                    }
                  />
                </Form.Item>
              </Col>
            ))}
            <Col span={12}>
              <Form.Item name="zhCtaText" label={`${t("adminExperts.fieldCta")} · ${t("adminExperts.contentChinese")}`}>
                <Input placeholder={t("adminExperts.ctaPlaceholder")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="enCtaText" label={`${t("adminExperts.fieldCta")} · ${t("adminExperts.contentEnglish")}`}>
                <Input placeholder={t("adminExperts.ctaPlaceholder")} />
              </Form.Item>
            </Col>
          </Row>

          <p className="mb-3 mt-5 text-sm font-semibold text-[#111827]">MCP Connectors</p>
          <Row>
            <Col span={16}>
              <Form.Item name="mcpConnectorIds" extra="选择此 Expert 可使用的 MCP Connectors（可选）">
                <Select
                  mode="multiple"
                  allowClear
                  loading={referencesLoading}
                  placeholder="选择 MCP Connectors"
                  options={mcpConnectors.map((c) => ({ value: c.id, label: c.name }))}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
