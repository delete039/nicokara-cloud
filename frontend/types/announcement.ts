export type Announcement = {
  id: string;
  enabled: true;
  title: string;
  version?: string;
  publishedAt?: string;
  content: string[];
  buttonLabel: string;
};

export type AnnouncementBundle = {
  current: Announcement;
  history: Announcement[];
};
