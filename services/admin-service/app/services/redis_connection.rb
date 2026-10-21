module RedisConnection
  DEFAULT_TIMEOUT = 2

  def self.url
    ENV.fetch('REDIS_URL') do
      "redis://#{ENV.fetch('REDIS_HOST', 'localhost')}:#{ENV.fetch('REDIS_PORT', '6379')}/0"
    end
  end

  def self.build(timeout: DEFAULT_TIMEOUT)
    Redis.new(url: url, timeout: timeout)
  end
end
