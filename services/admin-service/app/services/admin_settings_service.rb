class AdminSettingsService
  AUTO_INVESTIGATE_KEY = 'admin:auto_investigate'.freeze

  class << self
    def auto_investigate_enabled?
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL',
                       "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      # Default to true (existing behavior) if not explicitly set
      val = redis.get(AUTO_INVESTIGATE_KEY)
      val.nil? || val == 'true'
    rescue StandardError => e
      Rails.logger.error("Failed to read auto_investigate setting: #{e.message}")
      true # fail-open to preserve existing behavior
    ensure
      redis&.close
    end

    def set_auto_investigate(enabled)
      redis = Redis.new(
        url: ENV.fetch('REDIS_URL',
                       "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"),
        timeout: 2
      )
      redis.set(AUTO_INVESTIGATE_KEY, enabled.to_s)
    rescue StandardError => e
      Rails.logger.error("Failed to set auto_investigate setting: #{e.message}")
      raise
    ensure
      redis&.close
    end
  end
end
