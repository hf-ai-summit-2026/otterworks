require 'rails_helper'

RSpec.describe AuditLogger do
  let(:jwt_user_id) { SecureRandom.uuid }
  let(:request) do
    ActionDispatch::TestRequest.create(
      'jwt.user_id' => jwt_user_id,
      'jwt.user_email' => 'jwt-admin@test.com',
      'REMOTE_ADDR' => '203.0.113.7',
      'HTTP_USER_AGENT' => 'AuditLogger Spec'
    )
  end

  describe '.log' do
    it 'derives actor, IP and user agent from the request' do
      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          changes_made: { role: 'admin' })

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'user.updated',
        resource_type: 'AdminUser',
        actor_id: jwt_user_id,
        actor_email: 'jwt-admin@test.com',
        ip_address: '203.0.113.7',
        user_agent: 'AuditLogger Spec',
        changes_made: { 'role' => 'admin' }
      )
    end

    it 'prefers explicit actor arguments over request values' do
      explicit_id = SecureRandom.uuid
      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          actor_id: explicit_id, actor_email: 'explicit@test.com')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_id, actor_email: 'explicit@test.com')
    end

    it 'records an entry without a request' do
      expect do
        described_class.log(action: 'config.updated', resource_type: 'SystemConfig')
      end.to change(AuditLog, :count).by(1)

      expect(AuditLog.last).to have_attributes(actor_id: nil, ip_address: nil, user_agent: nil)
    end

    it 'swallows and logs errors instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser')
      end.not_to raise_error

      expect(AuditLog.count).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
