module EnvHelper
  def with_env(vars)
    previous = vars.keys.index_with { |key| ENV.fetch(key, nil) }
    vars.each { |key, value| ENV[key] = value }
    yield
  ensure
    previous.each { |key, value| ENV[key] = value }
  end
end

RSpec.configure do |config|
  config.include EnvHelper
end
