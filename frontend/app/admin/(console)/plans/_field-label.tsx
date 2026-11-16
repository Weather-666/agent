import { Tooltip } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";

// Shared field label for the plan modal: keeps the required asterisk and the
// optional tooltip icon in a consistent position across every field.
export function FieldLabel({ text, required, tooltip }: { text: string; required?: boolean; tooltip?: string }) {
  return (
    <label className="mb-1 flex items-center gap-1.5 text-sm text-[#4b5563]">
      <span>
        {text}
        {required ? <span className="ml-0.5 text-[#d94848]">*</span> : null}
      </span>
      {tooltip ? (
        <Tooltip title={tooltip}>
          <QuestionCircleOutlined className="text-[#6b7280]" />
        </Tooltip>
      ) : null}
    </label>
  );
}
