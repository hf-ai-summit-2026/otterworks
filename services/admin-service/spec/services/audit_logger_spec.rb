require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    let(:jwt_user_id) { SecureRandom.uuid }
    let(:resource_id) { SecureRandom.uuid }
    let(:request) do
      ActionDispatch::TestRequest.create(
        'jwt.user_id' => jwt_user_id,
        'jwt.user_email' => 'actor@example.test',
        'REMOTE_ADDR' => '10.0.0.5',
        'HTTP_USER_AGENT' => 'RSpec Agent'
      )
    end

    it 'records an audit log with actor and client details from the request' do
      expect do
        described_class.log(action: 'config.updated', resource_type: 'SystemConfig', resource_id: resource_id,
                            request: request, changes_made: { 'key' => 'value' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'config.updated',
        resource_type: 'SystemConfig',
        resource_id: resource_id,
        actor_id: jwt_user_id,
        actor_email: 'actor@example.test',
        ip_address: '10.0.0.5',
        user_agent: 'RSpec Agent',
        changes_made: { 'key' => 'value' }
      )
    end

    it 'prefers explicitly passed actor details over the request JWT claims' do
      explicit_id = SecureRandom.uuid
      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          actor_id: explicit_id, actor_email: 'explicit@example.test')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_id, actor_email: 'explicit@example.test')
    end

    it 'records without a request' do
      described_class.log(action: 'quota.updated', resource_type: 'StorageQuota')

      expect(AuditLog.last).to have_attributes(actor_id: nil, actor_email: nil, ip_address: nil, user_agent: nil)
    end

    it 'swallows and logs persistence errors instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser')
      end.not_to raise_error

      expect(AuditLog.count).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
