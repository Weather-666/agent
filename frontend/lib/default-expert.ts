export const DEFAULT_EXPERT_SELECTION_ID = "__winwise_default__";
export const DEFAULT_EXPERT_CATEGORY_ID = "__default__";

export type ExpertSelectionCard = {
  id: string;
  categoryId: string;
  categoryName: string;
  short: string;
  title: string;
  description: string;
  starter: string;
  isAccessible: boolean;
};

export function createDefaultExpertCard(copy: {
  title: string;
  categoryName: string;
  description: string;
  starter: string;
}): ExpertSelectionCard {
  return {
    id: DEFAULT_EXPERT_SELECTION_ID,
    categoryId: DEFAULT_EXPERT_CATEGORY_ID,
    categoryName: copy.categoryName,
    short: "W",
    title: copy.title,
    description: copy.description,
    starter: copy.starter,
    isAccessible: true,
  };
}

export function isDefaultExpertSelection(expertId: string | null | undefined) {
  return expertId === DEFAULT_EXPERT_SELECTION_ID;
}
