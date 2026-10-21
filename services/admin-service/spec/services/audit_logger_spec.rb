require 'rails_helper'

RSpec.describe AuditLogger do
  let(:jwt_user_id) { SecureRandom.uuid }
  let(:resource_id) { SecureRandom.uuid }
  let(:explicit_actor_id) { SecureRandom.uuid }

  let(:request) do
    ActionDispatch::TestRequest.create(
      'jwt.user_id' => jwt_user_id,
      'jwt.user_email' => 'jwt@example.com',
      'REMOTE_ADDR' => '203.0.113.7',
      'HTTP_USER_AGENT' => 'RSpec Agent'
    )
  end

  describe '.log' do
    it 'records an audit log with actor and request details taken from the request' do
      expect do
        described_class.log(action: 'user.updated', resource_type: 'AdminUser', resource_id: resource_id,
                            request: request,
                            changes_made: { role: 'admin' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'user.updated',
        resource_type: 'AdminUser',
        resource_id: resource_id,
        actor_id: jwt_user_id,
        actor_email: 'jwt@example.com',
        ip_address: '203.0.113.7',
        user_agent: 'RSpec Agent',
        changes_made: { 'role' => 'admin' }
      )
    end

    it 'prefers explicitly passed actor details over the JWT claims on the request' do
      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          actor_id: explicit_actor_id, actor_email: 'explicit@example.com')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_actor_id, actor_email: 'explicit@example.com')
    end

    it 'records an entry without a request' do
      described_class.log(action: 'config.updated', resource_type: 'SystemConfig')

      expect(AuditLog.last).to have_attributes(actor_id: nil, actor_email: nil, ip_address: nil, user_agent: nil)
    end

    it 'does not raise and logs an error when recording fails' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser', request: request)
      end.not_to change(AuditLog, :count)

      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
