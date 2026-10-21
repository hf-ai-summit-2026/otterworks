FactoryBot.define do
  factory :incident do
    title { 'Elevated error rate' }
    description { 'Error rate above threshold' }
    severity { 'high' }
    status { 'open' }
    affected_service { 'search-service' }

    trait :investigating do
      status { 'investigating' }
    end

    trait :resolved do
      status { 'resolved' }
      resolved_at { Time.current }
    end

    trait :with_running_session do
      status { 'investigating' }
      devin_session_id { "session-#{SecureRandom.hex(4)}" }
      devin_session_url { 'https://app.devin.ai/sessions/example' }
      devin_session_status { 'running' }
    end
  end
end
