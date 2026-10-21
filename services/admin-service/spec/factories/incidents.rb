FactoryBot.define do
  factory :incident do
    title { 'Elevated error rate' }
    description { 'Error rate above threshold' }
    severity { 'high' }
    status { 'open' }
    affected_service { 'search-service' }
  end
end
