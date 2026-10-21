FactoryBot.define do
  factory :incident do
    title { Faker::Lorem.sentence(word_count: 5) }
    description { Faker::Lorem.paragraph }
    severity { 'medium' }
    status { 'open' }
    affected_service { 'admin-service' }

    trait :investigating do
      status { 'investigating' }
    end

    trait :resolved do
      status { 'resolved' }
      resolved_at { 1.hour.ago }
    end

    trait :closed do
      status { 'closed' }
      resolved_at { 2.hours.ago }
      closed_at { 1.hour.ago }
    end

    trait :with_running_session do
      sequence(:devin_session_id) { |n| "devin-session-#{n}" }
      devin_session_status { 'running' }
    end
  end
end
