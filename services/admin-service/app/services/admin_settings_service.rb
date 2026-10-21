class AdminSettingsService
  AUTO_INVESTIGATE_KEY = 'admin:auto_investigate'.freeze

  class << self
    def auto_investigate_enabled?
      # Default to true (existing behavior) if not explicitly set
      val = with_redis { |redis| redis.get(AUTO_INVESTIGATE_KEY) }
      val.nil? || val == 'true'
    rescue StandardError => e
      Rails.logger.error("Failed to read auto_investigate setting: #{e.message}")
      true # fail-open to preserve existing behavior
    end

    def set_auto_investigate(enabled) # rubocop:disable Naming/AccessorMethodName
      with_redis { |redis| redis.set(AUTO_INVESTIGATE_KEY, enabled.to_s) }
    rescue StandardError => e
      Rails.logger.error("Failed to set auto_investigate setting: #{e.message}")
      raise
    end

    private

    def with_redis
      redis = RedisConnection.build
      yield redis
    ensure
      redis&.close
    end
  end
end
