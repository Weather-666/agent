"use client";

import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  type TableColumnsType,
  type UploadFile,
} from "antd";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import {
  deleteSkill,
  getSkillFileText,
  getSkills,
  type Skill,
  updateSkill,
  uploadSkill,
} from "@/lib/api/admin-client";
import type { ApiError } from "@/lib/request";
import { useI18n, type Translate } from "@/lib/i18n";

const { Title, Text } = Typography;


const PAGE_SIZE = 20;

function formatDate(value?: string) {
  if (!value) return "-";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function normalizeListText(value: string) {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function getErrorMessage(error: unknown, fallback: string) {
  const apiError = error as Partial<ApiError>;
  return apiError?.message || fallback;
}

function getSkillUploadErrorMessage(error: unknown, t: Translate) {
  const message = getErrorMessage(error, t("adminSkills.uploadFailed"));

  if (
    message.includes("SKILL.md frontmatter requires name") ||
    message.includes("frontmatter requires name")
  ) {
    return t("adminSkills.uploadFailedMissingName");
  }

  if (
    message.includes("SKILL.md frontmatter requires description") ||
    message.includes("frontmatter requires description")
  ) {
    return t("adminSkills.uploadFailedMissingDescription");
  }

  if (message.includes("SKILL_METADATA_REQUIRED")) {
    return t("adminSkills.uploadFailedMissingMetadata");
  }

  return message;
}

type EditFormValues = {
  name: string;
  description: string;
  version: string;
  tags: string;
  allowedTools: string;
};

export default function AdminSkillsManagePage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const [editForm] = Form.useForm<EditFormValues>();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadSlug, setUploadSlug] = useState("");
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null);
  const [deleteFiles, setDeleteFiles] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewContent, setPreviewContent] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);

  const totalLabel = useMemo(() => t("adminSkills.totalLabel", { count: total }), [t, total]);

  async function loadSkills(nextOffset = offset, nextSearch = search, nextLimit = pageSize) {
    setLoading(true);

    try {
      const data = await getSkills({
        search: nextSearch.trim() || undefined,
        limit: nextLimit,
        offset: nextOffset,
      });
      setSkills(data.items ?? []);
      setTotal(data.total ?? 0);
      setOffset(data.offset ?? nextOffset);
    } catch (loadError) {
      message.error(getErrorMessage(loadError, t("adminSkills.loadFailed")));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void Promise.resolve().then(() => loadSkills(0, ""));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openEdit(skill: Skill) {
    setEditingSkill(skill);
    editForm.setFieldsValue({
      name: skill.name ?? "",
      description: skill.description ?? "",
      version: skill.version ?? "",
      tags: (skill.tags ?? []).join(", "),
      allowedTools: (skill.allowedTools ?? []).join("\n"),
    });
  }

  function closeUploadModal() {
    if (submitting) return;
    setUploadOpen(false);
    setUploadFile(null);
    setUploadSlug("");
  }

  async function handleSearch(value: string) {
    const nextSearch = value.trim();
    setSearch(nextSearch);
    await loadSkills(0, nextSearch);
  }

  async function handleUpload() {
    if (!uploadFile) {
      message.error(t("adminSkills.selectZipFile"));
      return;
    }

    setSubmitting(true);

    try {
      await uploadSkill(uploadFile, uploadSlug);
      setUploadFile(null);
      setUploadSlug("");
      setUploadOpen(false);
      message.success(t("adminSkills.uploadSuccess"));
      await loadSkills(0, search);
    } catch (uploadError) {
      message.error(getSkillUploadErrorMessage(uploadError, t));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUpdate(values: EditFormValues) {
    if (!editingSkill) return;

    setSubmitting(true);

    try {
      await updateSkill(editingSkill.slug, {
        name: values.name.trim() || undefined,
        description: values.description.trim() || undefined,
        version: values.version.trim() || undefined,
        tags: normalizeListText(values.tags),
        allowedTools: normalizeListText(values.allowedTools),
      });
      setEditingSkill(null);
      message.success(t("adminSkills.updateSuccess"));
      await loadSkills(offset, search);
    } catch (updateError) {
      message.error(getErrorMessage(updateError, t("adminSkills.updateFailed")));
    } finally {
      setSubmitting(false);
    }
  }

  function handleDelete(skill: Skill) {
    modal.confirm({
      title: t("adminSkills.deleteButton"),
      content: t("adminSkills.deleteConfirm", {
        name: skill.name || skill.slug,
        extra: deleteFiles ? t("adminSkills.deleteConfirmFilesSuffix") : "",
      }),
      okText: t("adminSkills.deleteButton"),
      okButtonProps: { danger: true },
      cancelText: t("adminSkills.cancel"),
      onOk: async () => {
        try {
          await deleteSkill(skill.slug, deleteFiles);
          message.success(t("adminSkills.deleteSuccess"));
          await loadSkills(Math.max(0, offset - (skills.length === 1 ? pageSize : 0)), search);
        } catch (deleteError) {
          message.error(getErrorMessage(deleteError, t("adminSkills.deleteFailed")));
        }
      },
    });
  }

  async function handlePreview(skill: Skill) {
    setPreviewTitle(`${skill.slug}/SKILL.md`);
    setPreviewContent("");
    setPreviewOpen(true);
    setPreviewLoading(true);

    try {
      const text = await getSkillFileText(skill.slug);
      setPreviewContent(text);
    } catch (previewError) {
      message.error(getErrorMessage(previewError, t("adminSkills.previewFailed")));
      setPreviewOpen(false);
      setPreviewTitle("");
    } finally {
      setPreviewLoading(false);
    }
  }

  const uploadFileList: UploadFile[] = uploadFile
    ? [{ uid: "-1", name: uploadFile.name, status: "done" }]
    : [];

  const columns: TableColumnsType<Skill> = [
    {
      title: t("adminSkills.columnName"),
      key: "name",
      render: (_, skill) => (
        <div>
          <p className="m-0 text-sm text-[#111827]">{skill.name || "-"}</p>
          <p className="m-0 mt-1 max-w-[260px] truncate text-xs text-[#8a8f98]">
            {skill.description || t("adminSkills.noDescription")}
          </p>
        </div>
      ),
    },
    { title: "Slug", dataIndex: "slug", key: "slug" },
    { title: t("adminSkills.columnVersion"), key: "version", render: (_, skill) => skill.version || "-" },
    {
      title: t("adminSkills.columnTags"),
      key: "tags",
      render: (_, skill) =>
        (skill.tags ?? []).length ? (
          <Space size={[4, 4]} wrap className="max-w-[220px]">
            {skill.tags?.map((tag) => (
              <Tag key={tag} className="!m-0">{tag}</Tag>
            ))}
          </Space>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    { title: t("adminSkills.columnFileCount"), key: "fileCount", render: (_, skill) => skill.filePaths?.length ?? 0 },
    { title: t("adminSkills.columnUpdatedAt"), key: "updatedAt", render: (_, skill) => formatDate(skill.updatedAt) },
    {
      title: t("adminSkills.columnActions"),
      key: "actions",
      fixed: "right",
      width: 240,
      render: (_, skill) => (
        <Space wrap>
          <Button size="small" onClick={() => openEdit(skill)}>{t("adminSkills.editButton")}</Button>
          <Button size="small" onClick={() => void handlePreview(skill)}>{t("adminSkills.viewSkillMd")}</Button>
          <Button size="small" danger disabled={submitting} onClick={() => handleDelete(skill)}>
            {t("adminSkills.deleteButton")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#6b7280]">{t("adminSkills.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminSkills.title")}</Title>
      </div>

      <Card>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Title level={4} className="!mb-1">{t("adminSkills.listTitle")}</Title>
            <Text type="secondary" className="text-sm">{t("adminSkills.listDescription")}</Text>
          </div>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
            {t("adminSkills.uploadButton")}
          </Button>
        </div>

        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <Input.Search
            allowClear
            defaultValue={search}
            onSearch={handleSearch}
            placeholder={t("adminSkills.searchPlaceholder")}
            enterButton={t("adminSkills.searchButton")}
            style={{ width: 360 }}
          />
          <Space>
            <Text type="secondary" className="text-sm">{loading ? t("adminSkills.loading") : totalLabel}</Text>
            <Checkbox checked={deleteFiles} onChange={(event) => setDeleteFiles(event.target.checked)}>
              {t("adminSkills.deleteFilesLabel")}
            </Checkbox>
          </Space>
        </div>

        <Table<Skill>
          rowKey="slug"
          columns={columns}
          dataSource={skills}
          loading={loading}
          scroll={{ x: 960 }}
          locale={{ emptyText: t("adminSkills.emptyState") }}
          pagination={{
            current: Math.floor(offset / pageSize) + 1,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            onChange: (nextPage, nextPageSize) => {
              setPageSize(nextPageSize);
              void loadSkills((nextPage - 1) * nextPageSize, search, nextPageSize);
            },
          }}
        />
      </Card>

      <Modal
        open={uploadOpen}
        title={t("adminSkills.uploadButton")}
        width={720}
        onCancel={closeUploadModal}
        okText={submitting ? t("adminSkills.uploading") : t("adminSkills.upload")}
        okButtonProps={{ loading: submitting }}
        cancelText={t("adminSkills.cancel")}
        onOk={() => void handleUpload()}
        mask={{ closable: false }}
      >
        <Text type="secondary" className="mb-3 block text-sm">{t("adminSkills.listDescription")}</Text>

        <div className="grid gap-3">
          <div>
            <label className="mb-1 block text-sm text-[#1f2933]">{t("adminSkills.fileLabel")}</label>
            <Upload
              accept=".zip,application/zip,application/x-zip-compressed"
              maxCount={1}
              fileList={uploadFileList}
              beforeUpload={(file) => {
                setUploadFile(file);
                return false;
              }}
              onRemove={() => setUploadFile(null)}
            >
              <Button icon={<UploadOutlined />}>{t("adminSkills.fileLabel")}</Button>
            </Upload>
          </div>
          <div>
            <label className="mb-1 block text-sm text-[#1f2933]">{t("adminSkills.slugLabel")}</label>
            <Input value={uploadSlug} onChange={(event) => setUploadSlug(event.target.value)} placeholder="lowercase-slug" />
          </div>

          <div className="rounded-[8px] border border-[#dbe4f0] bg-[#fafafa] p-3 text-sm text-[#4b5563]">
            <p className="mb-2 font-medium text-[#111827]">{t("adminSkills.frontmatterHint")}</p>
            <pre className="overflow-x-auto rounded-[8px] bg-[#111827] p-3 text-xs leading-5 text-white">{`---
name: amazon-review-analyzer
description: Analyze Amazon review trends and customer feedback.
version: 1.0.0
allowed-tools:
  - Bash(python scripts/analyze_reviews.py:*)
tags:
  - amazon
  - reviews
---`}</pre>
            <p className="mt-2 text-xs text-[#8a8f98]">{t("adminSkills.frontmatterNote")}</p>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(editingSkill)}
        title={t("adminSkills.editModalTitle")}
        width={640}
        onCancel={() => setEditingSkill(null)}
        okText={submitting ? t("adminSkills.saving") : t("adminSkills.save")}
        okButtonProps={{ loading: submitting }}
        cancelText={t("adminSkills.cancel")}
        onOk={() => editForm.submit()}
      >
        {editingSkill ? (
          <Text type="secondary" className="mb-3 block text-sm">
            {t("adminSkills.slugNotEditable", { slug: editingSkill.slug })}
          </Text>
        ) : null}
        <Form<EditFormValues> form={editForm} layout="vertical" onFinish={handleUpdate}>
          <Form.Item name="name" label={t("adminSkills.columnName")}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label={t("adminSkills.fieldDescription")}>
            <Input.TextArea rows={3} />
          </Form.Item>
          <div className="grid gap-x-4 md:grid-cols-2">
            <Form.Item name="version" label={t("adminSkills.columnVersion")}>
              <Input />
            </Form.Item>
            <Form.Item name="tags" label={t("adminSkills.fieldTags")}>
              <Input />
            </Form.Item>
          </div>
          <Form.Item name="allowedTools" label={t("adminSkills.fieldAllowedTools")}>
            <Input.TextArea rows={4} className="!font-mono" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={previewOpen}
        title={
          <div>
            <div>{t("adminSkills.previewModalTitle")}</div>
            <Text type="secondary" className="text-sm font-normal">{previewTitle}</Text>
          </div>
        }
        width={760}
        footer={null}
        onCancel={() => {
          setPreviewOpen(false);
          setPreviewTitle("");
          setPreviewContent("");
        }}
      >
        {previewLoading ? (
          <div className="grid place-items-center py-10"><Spin /></div>
        ) : (
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-[8px] bg-[#111827] p-4 text-xs leading-6 text-[#f8fafc]">
            {previewContent}
          </pre>
        )}
      </Modal>
    </div>
  );
}
