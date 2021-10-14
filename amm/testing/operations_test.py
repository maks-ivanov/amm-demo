import algosdk
from math import sqrt

import pytest

from algosdk import account, encoding
from algosdk.logic import get_application_address

from amm.operations import createAmmApp, setupAmmApp, supply, withdraw, swap, closeAmm
from amm.util import getBalances, getAppGlobalState, getLastBlockTimestamp
from amm.testing.setup import getAlgodClient
from amm.testing.resources import getTemporaryAccount, optInToAsset, createDummyAsset


def is_close(a, b, e=1):
    return abs(a - b) <= e


def test_create():
    client = getAlgodClient()
    creator = getTemporaryAccount(client)

    tokenA = 1
    tokenB = 2
    poolToken = 3
    feeBps = -30
    minIncrement = 1000

    with pytest.raises(OverflowError):
        createAmmApp(client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement)

    feeBps = 0
    with pytest.raises(algosdk.error.AlgodHTTPError) as e:
        createAmmApp(client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement)
        assert "logic eval error: assert failed" in str(e)

    feeBps = 30
    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    # fee too high?
    actual = getAppGlobalState(client, appID)
    expected = {
        b"creator": encoding.decode_address(creator.getAddress()),
        b"token_a_key": tokenA,
        b"token_b_key": tokenB,
        b"pool_token_key": poolToken,
        b"fee_bps_key": feeBps,
        b"min_increment_key": minIncrement,
        b"pool_tokens_outstanding_key": 0,
    }

    assert actual == expected


def test_setup():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)
    funder = getTemporaryAccount(client)

    tokenAAmount = 1_000_000
    tokenBAmount = 2_000_000
    poolTokenAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenAAmount, funder)
    tokenB = createDummyAsset(client, tokenBAmount, funder)
    poolToken = createDummyAsset(client, poolTokenAmount, funder)
    feeBps = 30
    minIncrement = 1000

    # might be an issue - pool tokens are created and deposited separately
    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    setupAmmApp(
        client=client,
        appID=appID,
        funder=funder,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenAmount=poolTokenAmount,
    )

    actualState = getAppGlobalState(client, appID)
    expectedState = {
        b"creator": encoding.decode_address(creator.getAddress()),
        b"token_a_key": tokenA,
        b"token_b_key": tokenB,
        b"pool_token_key": poolToken,
        b"fee_bps_key": feeBps,
        b"min_increment_key": minIncrement,
        b"pool_tokens_outstanding_key": 0,
    }

    assert actualState == expectedState

    actualBalances = getBalances(client, get_application_address(appID))
    # todo
    expectedBalances = {0: 1_100_000, tokenA: 0, tokenB: 0, poolToken: poolTokenAmount}

    assert actualBalances == expectedBalances


def test_before_setup():
    client = getAlgodClient()
    creator = getTemporaryAccount(client)

    tokenA = 1
    tokenB = 2
    poolToken = 3
    feeBps = 30
    minIncrement = 1000

    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    ops = [
        lambda: supply(client, appID, 10, 10, creator),
        lambda: withdraw(client, appID, 10, creator),
        lambda: swap(client, appID, 10, tokenA, creator),
    ]

    for op in ops:
        with pytest.raises(algosdk.error.AlgodHTTPError) as e:
            op()
            assert "logic eval error: assert failed" in str(e)

    closeAmm(client, appID, creator)


def test_supply():
    client = getAlgodClient()

    creator = getTemporaryAccount(client)

    tokenAAmount = 1_000_000
    tokenBAmount = 2_000_000
    poolTokenAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenAAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    poolToken = createDummyAsset(client, poolTokenAmount, creator)
    feeBps = 30
    minIncrement = 1000

    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenAmount=poolTokenAmount,
    )

    supply(client, appID, 1000, 2000, creator)
    actualTokensOutstanding = getAppGlobalState(client, appID)[
        b"pool_tokens_outstanding_key"
    ]
    expectedTokensOutstanding = int(sqrt(1000 * 2000))
    firstPoolTokens = getBalances(client, creator.getAddress())[poolToken]
    assert actualTokensOutstanding == expectedTokensOutstanding
    assert firstPoolTokens == expectedTokensOutstanding

    # should take 1000 : 2000 again
    supply(client, appID, 2000, 2000, creator)
    actualTokensOutstanding = getAppGlobalState(client, appID)[
        b"pool_tokens_outstanding_key"
    ]
    expectedTokensOutstanding = firstPoolTokens * 2
    secondPoolTokens = (
        getBalances(client, creator.getAddress())[poolToken] - firstPoolTokens
    )
    assert actualTokensOutstanding == expectedTokensOutstanding
    assert secondPoolTokens == firstPoolTokens

    # should take 10000 : 20000
    supply(client, appID, 12000, 20000, creator)
    actualTokensOutstanding = getAppGlobalState(client, appID)[
        b"pool_tokens_outstanding_key"
    ]
    expectedTokensOutstanding = firstPoolTokens * 12  # 2 + 10
    thirdPoolTokens = (
        getBalances(client, creator.getAddress())[poolToken]
        - secondPoolTokens
        - firstPoolTokens
    )
    assert actualTokensOutstanding == expectedTokensOutstanding
    assert thirdPoolTokens == firstPoolTokens * 10


def test_withdraw():
    client = getAlgodClient()
    creator = getTemporaryAccount(client)

    tokenAAmount = 1_000_000
    tokenBAmount = 2_000_000
    poolTokenAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenAAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    poolToken = createDummyAsset(client, poolTokenAmount, creator)
    feeBps = 30
    minIncrement = 1000

    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenAmount=poolTokenAmount,
    )

    supply(client, appID, 1000, 2000, creator)
    initialPoolTokensOutstanding = int(sqrt(1000 * 2000))

    # return one third of pool tokens to the pool, keep two thirds
    withdraw(client, appID, initialPoolTokensOutstanding // 3, creator)

    firstPoolTokens = getBalances(client, creator.getAddress())[poolToken]
    expectedPoolTokens = (
        initialPoolTokensOutstanding - initialPoolTokensOutstanding // 3
    )
    assert firstPoolTokens == expectedPoolTokens

    firstTokenAAmount = getBalances(client, creator.getAddress())[tokenA]
    expectedTokenAAmount = tokenAAmount - 1000 + 1000 // 3
    assert firstTokenAAmount == expectedTokenAAmount

    firstTokenBAmount = getBalances(client, creator.getAddress())[tokenB]
    expectedTokenBAmount = tokenBAmount - 2000 + 2000 // 3
    assert firstTokenBAmount == expectedTokenBAmount

    # double the original liquidity
    supply(client, appID, 1000 + 1000 // 3, 2000 + 2000 // 3, creator)
    actualTokensOutstanding = getAppGlobalState(client, appID)[
        b"pool_tokens_outstanding_key"
    ]
    assert is_close(actualTokensOutstanding, initialPoolTokensOutstanding * 2)

    withdraw(client, appID, initialPoolTokensOutstanding, creator)

    poolBalances = getBalances(client, get_application_address(appID))

    expectedTokenAAmount = 1000
    expectedTokenBAmount = 2000
    supplierPoolTokens = getBalances(client, creator.getAddress())[poolToken]
    assert is_close(poolBalances[tokenA], expectedTokenAAmount)
    assert is_close(poolBalances[tokenB], expectedTokenBAmount)
    assert is_close(supplierPoolTokens, initialPoolTokensOutstanding)


def test_swap():
    client = getAlgodClient()
    creator = getTemporaryAccount(client)
    tokenAAmount = 1_000_000_000
    tokenBAmount = 2_000_000_000
    poolTokenAmount = 10 ** 13
    tokenA = createDummyAsset(client, tokenAAmount, creator)
    tokenB = createDummyAsset(client, tokenBAmount, creator)
    poolToken = createDummyAsset(client, poolTokenAmount, creator)
    feeBps = 30
    minIncrement = 1000

    appID = createAmmApp(
        client, creator, tokenA, tokenB, poolToken, feeBps, minIncrement
    )

    setupAmmApp(
        client=client,
        appID=appID,
        funder=creator,
        tokenA=tokenA,
        tokenB=tokenB,
        poolToken=poolToken,
        poolTokenAmount=poolTokenAmount,
    )

    m, n = 100_000_000, 200_000_000
    supply(client, appID, m, n, creator)

    with pytest.raises(algosdk.error.AlgodHTTPError) as e:
        # swap wrong token
        swap(client, appID, poolToken, 1, creator)
        assert "logic eval error: assert failed" in str(e)

    x = 2_000_000
    swap(client, appID, tokenA, x, creator)
    initialProduct = m * n
    expectedReceivedTokenB = n - initialProduct // (
        m + (100_00 - feeBps) * 2_000_000 // 100_00
    )

    poolBalances = getBalances(client, get_application_address(appID))
    actualReceivedTokenB = n - poolBalances[tokenB]
    actualSentTokenA = poolBalances[tokenA] - m
    assert actualSentTokenA == x
    assert actualReceivedTokenB == expectedReceivedTokenB

    expectedNewProduct = initialProduct - expectedReceivedTokenB * (m + x) + (x * n)
    actualNewProduct = poolBalances[tokenA] * poolBalances[tokenB]
    assert actualNewProduct == expectedNewProduct
    assert actualNewProduct > initialProduct


#
#
# def test_first_bid():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 10  # start time is 10 seconds in the future
#     endTime = startTime + 60  # end time is 1 minute after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     bidder = getTemporaryAccount(client)
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < startTime + 5:
#         sleep(startTime + 5 - lastRoundTime)
#
#     bidAmount = 500_000  # 0.5 Algos
#     placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)
#
#     actualState = getAppGlobalState(client, appID)
#     expectedState = {
#         b"seller": encoding.decode_address(seller.getAddress()),
#         b"nft_id": nftID,
#         b"start": startTime,
#         b"end": endTime,
#         b"reserve_amount": reserve,
#         b"min_bid_inc": increment,
#         b"num_bids": 1,
#         b"bid_amount": bidAmount,
#         b"bid_account": encoding.decode_address(bidder.getAddress()),
#     }
#
#     assert actualState == expectedState
#
#     actualBalances = getBalances(client, get_application_address(appID))
#     expectedBalances = {0: 2 * 100_000 + 2 * 1_000 + bidAmount, nftID: nftAmount}
#
#     assert actualBalances == expectedBalances
#
#
# def test_second_bid():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 10  # start time is 10 seconds in the future
#     endTime = startTime + 60  # end time is 1 minute after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     bidder1 = getTemporaryAccount(client)
#     bidder2 = getTemporaryAccount(client)
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < startTime + 5:
#         sleep(startTime + 5 - lastRoundTime)
#
#     bid1Amount = 500_000  # 0.5 Algos
#     placeBid(client=client, appID=appID, bidder=bidder1, bidAmount=bid1Amount)
#
#     bidder1AlgosBefore = getBalances(client, bidder1.getAddress())[0]
#
#     with pytest.raises(Exception):
#         bid2Amount = bid1Amount + 1_000  # increase is less than min increment amount
#         placeBid(
#             client=client,
#             appID=appID,
#             bidder=bidder2,
#             bidAmount=bid2Amount,
#         )
#
#     bid2Amount = bid1Amount + increment
#     placeBid(client=client, appID=appID, bidder=bidder2, bidAmount=bid2Amount)
#
#     actualState = getAppGlobalState(client, appID)
#     expectedState = {
#         b"seller": encoding.decode_address(seller.getAddress()),
#         b"nft_id": nftID,
#         b"start": startTime,
#         b"end": endTime,
#         b"reserve_amount": reserve,
#         b"min_bid_inc": increment,
#         b"num_bids": 2,
#         b"bid_amount": bid2Amount,
#         b"bid_account": encoding.decode_address(bidder2.getAddress()),
#     }
#
#     assert actualState == expectedState
#
#     actualAppBalances = getBalances(client, get_application_address(appID))
#     expectedAppBalances = {0: 2 * 100_000 + 2 * 1_000 + bid2Amount, nftID: nftAmount}
#
#     assert actualAppBalances == expectedAppBalances
#
#     bidder1AlgosAfter = getBalances(client, bidder1.getAddress())[0]
#
#     # bidder1 should receive a refund of their bid, minus the txn fee
#     assert bidder1AlgosAfter - bidder1AlgosBefore >= bid1Amount - 1_000
#
#
# def test_close_before_start():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 5 * 60  # start time is 5 minutes in the future
#     endTime = startTime + 60  # end time is 1 minute after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     assert lastRoundTime < startTime
#
#     closeAuction(client, appID, seller)
#
#     actualAppBalances = getBalances(client, get_application_address(appID))
#     expectedAppBalances = {0: 0}
#
#     assert actualAppBalances == expectedAppBalances
#
#     sellerNftBalance = getBalances(client, seller.getAddress())[nftID]
#     assert sellerNftBalance == nftAmount
#
#
# def test_close_no_bids():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 10  # start time is 10 seconds in the future
#     endTime = startTime + 30  # end time is 30 seconds after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < endTime + 5:
#         sleep(endTime + 5 - lastRoundTime)
#
#     closeAuction(client, appID, seller)
#
#     actualAppBalances = getBalances(client, get_application_address(appID))
#     expectedAppBalances = {0: 0}
#
#     assert actualAppBalances == expectedAppBalances
#
#     sellerNftBalance = getBalances(client, seller.getAddress())[nftID]
#     assert sellerNftBalance == nftAmount
#
#
# def test_close_reserve_not_met():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 10  # start time is 10 seconds in the future
#     endTime = startTime + 30  # end time is 30 seconds after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     bidder = getTemporaryAccount(client)
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < startTime + 5:
#         sleep(startTime + 5 - lastRoundTime)
#
#     bidAmount = 500_000  # 0.5 Algos
#     placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)
#
#     bidderAlgosBefore = getBalances(client, bidder.getAddress())[0]
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < endTime + 5:
#         sleep(endTime + 5 - lastRoundTime)
#
#     closeAuction(client, appID, seller)
#
#     actualAppBalances = getBalances(client, get_application_address(appID))
#     expectedAppBalances = {0: 0}
#
#     assert actualAppBalances == expectedAppBalances
#
#     bidderAlgosAfter = getBalances(client, bidder.getAddress())[0]
#
#     # bidder should receive a refund of their bid, minus the txn fee
#     assert bidderAlgosAfter - bidderAlgosBefore >= bidAmount - 1_000
#
#     sellerNftBalance = getBalances(client, seller.getAddress())[nftID]
#     assert sellerNftBalance == nftAmount
#
#
# def test_close_reserve_met():
#     client = getAlgodClient()
#
#     creator = getTemporaryAccount(client)
#     seller = getTemporaryAccount(client)
#
#     nftAmount = 1
#     nftID = createDummyAsset(client, nftAmount, seller)
#
#     startTime = int(time()) + 10  # start time is 10 seconds in the future
#     endTime = startTime + 30  # end time is 30 seconds after start
#     reserve = 1_000_000  # 1 Algo
#     increment = 100_000  # 0.1 Algo
#
#     appID = createAuctionApp(
#         client=client,
#         sender=creator,
#         seller=seller.getAddress(),
#         nftID=nftID,
#         startTime=startTime,
#         endTime=endTime,
#         reserve=reserve,
#         minBidIncrement=increment,
#     )
#
#     setupAuctionApp(
#         client=client,
#         appID=appID,
#         funder=creator,
#         nftHolder=seller,
#         nftID=nftID,
#         nftAmount=nftAmount,
#     )
#
#     sellerAlgosBefore = getBalances(client, seller.getAddress())[0]
#
#     bidder = getTemporaryAccount(client)
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < startTime + 5:
#         sleep(startTime + 5 - lastRoundTime)
#
#     bidAmount = reserve
#     placeBid(client=client, appID=appID, bidder=bidder, bidAmount=bidAmount)
#
#     optInToAsset(client, nftID, bidder)
#
#     _, lastRoundTime = getLastBlockTimestamp(client)
#     if lastRoundTime < endTime + 5:
#         sleep(endTime + 5 - lastRoundTime)
#
#     closeAuction(client, appID, seller)
#
#     actualAppBalances = getBalances(client, get_application_address(appID))
#     expectedAppBalances = {0: 0}
#
#     assert actualAppBalances == expectedAppBalances
#
#     bidderNftBalance = getBalances(client, bidder.getAddress())[nftID]
#
#     assert bidderNftBalance == nftAmount
#
#     actualSellerBalances = getBalances(client, seller.getAddress())
#
#     assert len(actualSellerBalances) == 2
#     # seller should receive the bid amount, minus the txn fee
#     assert actualSellerBalances[0] >= sellerAlgosBefore + bidAmount - 1_000
#     assert actualSellerBalances[nftID] == 0
