require 'rails_helper'

RSpec.describe AuditLogger do
  let(:resource_id) { SecureRandom.uuid }

  describe '.log' do
    it 'records an audit log with explicit actor details' do
      actor_id = SecureRandom.uuid

      expect do
        described_class.log(action: 'user.updated', resource_type: 'AdminUser', resource_id: resource_id,
                            actor_id: actor_id, actor_email: 'admin@example.com',
                            changes_made: { 'role' => 'admin' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(action: 'user.updated', resource_type: 'AdminUser', resource_id: resource_id,
                                     actor_id: actor_id, actor_email: 'admin@example.com',
                                     changes_made: { 'role' => 'admin' })
    end

    it 'derives actor, IP and user agent from the request' do
      actor_id = SecureRandom.uuid
      request = ActionDispatch::TestRequest.create(
        'jwt.user_id' => actor_id,
        'jwt.user_email' => 'jwt@example.com',
        'REMOTE_ADDR' => '10.1.2.3',
        'HTTP_USER_AGENT' => 'RSpec Agent'
      )

      described_class.log(action: 'config.updated', resource_type: 'SystemConfig', request: request)

      expect(AuditLog.last).to have_attributes(actor_id: actor_id, actor_email: 'jwt@example.com',
                                               ip_address: '10.1.2.3', user_agent: 'RSpec Agent')
    end

    it 'prefers explicit actor details over the request JWT claims' do
      explicit_id = SecureRandom.uuid
      request = ActionDispatch::TestRequest.create('jwt.user_id' => SecureRandom.uuid,
                                                   'jwt.user_email' => 'jwt@example.com')

      described_class.log(action: 'quota.updated', resource_type: 'StorageQuota', request: request,
                          actor_id: explicit_id, actor_email: 'explicit@example.com')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_id, actor_email: 'explicit@example.com')
    end

    it 'swallows and logs persistence errors instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser')
      end.not_to(change(AuditLog, :count))

      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
