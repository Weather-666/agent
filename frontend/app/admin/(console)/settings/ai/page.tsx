"use client";

import { Button, Card, Col, Form, Input, InputNumber, Row, Select, Typography } from "antd";
import { useI18n } from "@/lib/i18n";

const { Title, Text } = Typography;

export default function SettingsAiPage() {
  const { t } = useI18n();
  return (
    <div className="grid gap-[18px]">
      <div>
        <p className="text-xs uppercase tracking-[0.16em] text-[#8a8f98]">{t("adminSettings.eyebrow")}</p>
        <Title level={3} className="!mt-1 !mb-0">{t("adminSettings.ai.title")}</Title>
      </div>

      <Card
        styles={{ header: { paddingBlock: 16 }, body: { paddingTop: 16 } }}
        title={
          <div>
            <div className="text-[16px] text-[#1f2933]">{t("adminSettings.ai.heading")}</div>
            <Text type="secondary" className="text-[13px] font-normal">{t("adminSettings.ai.desc")}</Text>
          </div>
        }
      >
        <Form
          layout="vertical"
          initialValues={{ provider: "Anthropic Claude", version: "claude-sonnet", maxTokens: 2000, temperature: 0.7, timeout: 30 }}
        >
          <Row gutter={16}>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="provider" label={t("adminSettings.ai.provider")}>
                <Select options={[{ value: "Anthropic Claude" }, { value: "OpenAI" }]} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="version" label={t("adminSettings.ai.version")}>
                <Select options={[{ value: "claude-sonnet" }, { value: "gpt-4.1" }]} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="maxTokens" label={t("adminSettings.ai.maxTokens")}>
                <InputNumber style={{ width: "100%" }} min={0} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="temperature" label="Temperature">
                <InputNumber style={{ width: "100%" }} step={0.1} min={0} max={2} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} lg={8}>
              <Form.Item name="timeout" label={t("adminSettings.ai.timeout")}>
                <InputNumber style={{ width: "100%" }} min={0} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="systemPrompt" label="System Prompt">
                <Input.TextArea rows={4} placeholder={t("adminSettings.ai.systemPromptPlaceholder")} />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary">{t("adminSettings.ai.save")}</Button>
        </Form>
      </Card>
    </div>
  );
}
