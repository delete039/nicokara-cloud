export type Announcement = {
  id: string;
  enabled: true;
  title: string;
  version?: string;
  publishedAt?: string;
  content: string[];
  buttonLabel: string;
  rewardCode?: RewardCode;
};

export type RewardCode = {
  imageUrl: string;
  caption: string;
  alt: string;
};

export type AnnouncementBundle = {
  current: Announcement;
  history: Announcement[];
};
