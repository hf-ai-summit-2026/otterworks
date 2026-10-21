class MetricsAggregator
  def self.summary
    {
      timestamp: Time.current.iso8601,
      users: user_metrics,
      storage: storage_metrics,
      features: feature_metrics,
      announcements: announcement_metrics,
      audit: audit_metrics
    }
  end

  def self.user_metrics
    {
      total: AdminUser.count,
      active: AdminUser.active.count,
      suspended: AdminUser.suspended.count,
      by_role: AdminUser.group(:role).count,
      recent_signups: AdminUser.where('created_at >= ?', 30.days.ago).count
    }
  end

  def self.storage_metrics
    {
      total_allocated_bytes: StorageQuota.sum(:quota_bytes),
      total_used_bytes: StorageQuota.sum(:used_bytes),
      average_usage_percent: calculate_average_usage,
      users_over_quota: StorageQuota.over_quota.count,
      by_tier: StorageQuota.group(:tier).count
    }
  end

  def self.feature_metrics
    {
      total: FeatureFlag.count,
      enabled: FeatureFlag.enabled.count,
      disabled: FeatureFlag.disabled.count
    }
  end

  def self.announcement_metrics
    {
      total: Announcement.count,
      active: Announcement.active.count,
      by_severity: Announcement.group(:severity).count
    }
  end

  def self.audit_metrics
    {
      total_events: AuditLog.count,
      events_today: AuditLog.since(Time.current.beginning_of_day).count,
      events_this_week: AuditLog.since(1.week.ago).count,
      top_actions: AuditLog.since(1.week.ago).group(:action).order(count_all: :desc).limit(5).count
    }
  end

  def self.calculate_average_usage
    StorageQuota.average('(used_bytes::float / NULLIF(quota_bytes, 0)) * 100')&.round(2) || 0
  end

  private_class_method :calculate_average_usage
end
